using System.Net.Http;
using System.Text.Json;

namespace GeoV10.Core;

public sealed record IpLocation(string Country, string City, string State, string Isp, string Hostname,
                                string IpType, string IpVersion, double? Lat, double? Lon);

public sealed record GeoLocation(string Country, string State, string City);

/// <summary>Public IP, IP geolocation and reverse geocoding - same providers and order as the Python app.</summary>
public static class GeoServices
{
    private static readonly HttpClient Http = CreateClient();

    private static HttpClient CreateClient()
    {
        var c = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
        c.DefaultRequestHeaders.UserAgent.ParseAdd("GeoApp/8.33");
        return c;
    }

    private static string? S(JsonElement e, string k) =>
        e.TryGetProperty(k, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;

    private static string S(JsonElement e, string k, string fallback) =>
        S(e, k) is { Length: > 0 } v ? v : fallback;

    private static double? D(JsonElement e, string k) =>
        e.TryGetProperty(k, out var p) && p.ValueKind == JsonValueKind.Number && p.TryGetDouble(out var d) ? d : null;

    private static bool B(JsonElement e, string k) =>
        e.TryGetProperty(k, out var p) && p.ValueKind == JsonValueKind.True;

    public static async Task<string?> GetPublicIpAsync()
    {
        try
        {
            using var doc = JsonDocument.Parse(await Http.GetStringAsync("https://api.ipify.org?format=json"));
            var ip = S(doc.RootElement, "ip");
            if (!string.IsNullOrWhiteSpace(ip)) return ip;
        }
        catch { }
        try
        {
            var ip = (await Http.GetStringAsync("https://ipv4.icanhazip.com/")).Trim();
            if (ip.Length > 0) return ip;
        }
        catch { }
        return null;
    }

    public static async Task<IpLocation?> GetLocationDataAsync(string ip)
    {
        try
        {
            const string fields = "status,country,countryCode,region,regionName,city,isp,reverse,proxy,hosting,mobile,lat,lon";
            using var doc = JsonDocument.Parse(await Http.GetStringAsync($"http://ip-api.com/json/{ip}?fields={fields}"));
            var d = doc.RootElement;
            if (S(d, "status") != "success") return null;

            var ipType = B(d, "hosting") ? "Datacenter"
                       : B(d, "proxy") ? "Proxy/VPN"
                       : B(d, "mobile") ? "Mobile"
                       : "Residential";
            var hostname = S(d, "reverse");
            return new IpLocation(
                S(d, "country", "Unknown"),
                S(d, "city", "Unknown"),
                S(d, "regionName", "Unknown"),
                S(d, "isp", "Unknown"),
                string.IsNullOrEmpty(hostname) ? "No hostname" : hostname,
                ipType,
                ip.Contains(':') ? "IPv6" : "IPv4",
                D(d, "lat"), D(d, "lon"));
        }
        catch (Exception e)
        {
            Log.Line($"get_location_data error: {e.Message}");
            return null;
        }
    }

    public static async Task<GeoLocation?> GetLocationFromCoordinatesAsync(double lat, double lon)
    {
        var la = lat.ToString(System.Globalization.CultureInfo.InvariantCulture);
        var lo = lon.ToString(System.Globalization.CultureInfo.InvariantCulture);

        try
        {
            Log.Line($"Trying Nominatim for {la}, {lo}");
            using var doc = JsonDocument.Parse(await Http.GetStringAsync(
                $"https://nominatim.openstreetmap.org/reverse?lat={la}&lon={lo}&format=json&addressdetails=1"));
            if (doc.RootElement.TryGetProperty("address", out var a))
            {
                return new GeoLocation(
                    S(a, "country", "Unknown"),
                    S(a, "state") ?? S(a, "region") ?? S(a, "province") ?? "Unknown",
                    S(a, "city") ?? S(a, "town") ?? S(a, "village") ?? S(a, "municipality") ?? S(a, "county") ?? "Unknown");
            }
        }
        catch (Exception e) { Log.Line($"Nominatim error: {e.Message}"); }

        try
        {
            Log.Line($"Trying BigDataCloud for {la}, {lo}");
            using var doc = JsonDocument.Parse(await Http.GetStringAsync(
                $"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={la}&longitude={lo}&localityLanguage=en"));
            var d = doc.RootElement;
            return new GeoLocation(
                S(d, "countryName", "Unknown"),
                S(d, "principalSubdivision", "Unknown"),
                S(d, "city") is { Length: > 0 } c ? c : S(d, "locality", "Unknown"));
        }
        catch (Exception e) { Log.Line($"BigDataCloud error: {e.Message}"); }

        try
        {
            Log.Line($"Trying geocode.xyz for {la}, {lo}");
            using var doc = JsonDocument.Parse(await Http.GetStringAsync($"https://geocode.xyz/{la},{lo}?geoit=json"));
            var d = doc.RootElement;
            if (S(d, "country") is { Length: > 0 })
                return new GeoLocation(
                    S(d, "country", "Unknown"),
                    S(d, "state") ?? S(d, "region") ?? "Unknown",
                    S(d, "city", "Unknown"));
        }
        catch (Exception e) { Log.Line($"geocode.xyz error: {e.Message}"); }

        return null;
    }
}

/// <summary>Port of is_location_allowed(): alias-aware country/state matching.</summary>
public static class AllowedChecker
{
    private static readonly Dictionary<string, string[]> CountryAliases = new()
    {
        ["usa"] = new[] { "united states", "us", "usa", "america", "united states of america", "u.s.", "u.s.a." },
        ["uk"] = new[] { "united kingdom", "uk", "great britain", "england", "gb", "britain" },
        ["uae"] = new[] { "united arab emirates", "uae", "emirates" },
    };

    private static readonly Dictionary<string, string> StateAliases = new()
    {
        ["al"] = "alabama", ["ak"] = "alaska", ["az"] = "arizona", ["ar"] = "arkansas",
        ["ca"] = "california", ["co"] = "colorado", ["ct"] = "connecticut", ["de"] = "delaware",
        ["fl"] = "florida", ["ga"] = "georgia", ["hi"] = "hawaii", ["id"] = "idaho",
        ["il"] = "illinois", ["in"] = "indiana", ["ia"] = "iowa", ["ks"] = "kansas",
        ["ky"] = "kentucky", ["la"] = "louisiana", ["me"] = "maine", ["md"] = "maryland",
        ["ma"] = "massachusetts", ["mi"] = "michigan", ["mn"] = "minnesota", ["ms"] = "mississippi",
        ["mo"] = "missouri", ["mt"] = "montana", ["ne"] = "nebraska", ["nv"] = "nevada",
        ["nh"] = "new hampshire", ["nj"] = "new jersey", ["nm"] = "new mexico", ["ny"] = "new york",
        ["nc"] = "north carolina", ["nd"] = "north dakota", ["oh"] = "ohio", ["ok"] = "oklahoma",
        ["or"] = "oregon", ["pa"] = "pennsylvania", ["ri"] = "rhode island", ["sc"] = "south carolina",
        ["sd"] = "south dakota", ["tn"] = "tennessee", ["tx"] = "texas", ["ut"] = "utah",
        ["vt"] = "vermont", ["va"] = "virginia", ["wa"] = "washington", ["wv"] = "west virginia",
        ["wi"] = "wisconsin", ["wy"] = "wyoming", ["dc"] = "district of columbia",
        ["pr"] = "puerto rico", ["vi"] = "virgin islands", ["gu"] = "guam",
    };

    private static readonly HashSet<string> StateNames = new(StateAliases.Values);

    private static string NormalizeCountry(string c)
    {
        var lower = c.ToLowerInvariant().Trim();
        foreach (var (key, aliases) in CountryAliases)
            if (aliases.Contains(lower) || aliases.Any(a => lower.Contains(a) || a.Contains(lower)))
                return key;
        return lower;
    }

    private static string NormalizeState(string? s)
    {
        if (string.IsNullOrEmpty(s)) return "";
        var lower = s.ToLowerInvariant().Trim();
        return StateAliases.TryGetValue(lower, out var full) ? full : lower;
    }

    private static bool MatchesCountry(string allowed, string actual)
    {
        var a = NormalizeCountry(allowed);
        var b = NormalizeCountry(actual);
        return a == b || a.Contains(b) || b.Contains(a);
    }

    private static bool MatchesState(string allowed, string? actual)
    {
        if (string.IsNullOrEmpty(actual)) return false;
        var a = NormalizeState(allowed);
        var b = NormalizeState(actual);
        if (a == b) return true;
        var al = allowed.ToLowerInvariant().Trim();
        var ac = actual.ToLowerInvariant().Trim();
        if (StateAliases.TryGetValue(al, out var f1) && f1 == b) return true;
        if (StateAliases.TryGetValue(ac, out var f2) && f2 == a) return true;
        return a.Contains(b) || b.Contains(a);
    }

    /// <returns>(allowed, "country" | "state" | null)</returns>
    public static (bool ok, string? reason) IsAllowed(string? country, string? state,
        IReadOnlyList<string> allowedCountries, IReadOnlyList<string> allowedStates)
    {
        if (string.IsNullOrEmpty(country)) return (false, "country");
        if (!allowedCountries.Any(c => MatchesCountry(c, country))) return (false, "country");
        if (allowedStates.Count > 0 && !allowedStates.Any(s => MatchesState(s, state))) return (false, "state");
        return (true, null);
    }
}
