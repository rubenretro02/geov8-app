using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace GeoV10.Core;

public sealed record LocalLicense(string? LicenseKey, string? AgentName, string? ExpiresAt, string? Hwid);

/// <summary>
/// Port of SupabaseManager (v9.3.1.3+): persistent activation, offline grace,
/// fuzzy HWID lookup, device audit trail. Talks to PostgREST directly, like the
/// Python app, with the same tables and columns.
/// </summary>
public sealed class LicenseService
{
    private readonly HttpClient _http;
    private readonly string _base = AppInfo.SupabaseUrl + "/rest/v1";

    public string Hwid { get; }
    public IReadOnlyList<string> HwidCandidates { get; }

    public bool IsLicensed { get; private set; }
    public string? LicenseKey { get; private set; }
    public string AgentName { get; private set; } = "Agent";
    public int? DaysLeft { get; private set; }

    public LicenseService()
    {
        var hw = HardwareId.Get();
        Hwid = hw.Primary;
        HwidCandidates = hw.Candidates;

        _http = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
        _http.DefaultRequestHeaders.Add("apikey", AppInfo.SupabaseKey);
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", AppInfo.SupabaseKey);
        _http.DefaultRequestHeaders.Add("Prefer", "return=representation");
    }

    // ---------------------------------------------------------------- HTTP

    /// <summary>(reachable, rows). reachable=false means network/server error, never "empty".</summary>
    private async Task<(bool ok, JsonElement[] rows)> FetchAsync(string table, string query)
    {
        try
        {
            using var r = await _http.GetAsync($"{_base}/{table}?{query}");
            if (r.StatusCode != System.Net.HttpStatusCode.OK) return (false, Array.Empty<JsonElement>());
            var arr = await r.Content.ReadFromJsonAsync<JsonElement[]>();
            return (true, arr ?? Array.Empty<JsonElement>());
        }
        catch { return (false, Array.Empty<JsonElement>()); }
    }

    private async Task<bool> PatchAsync(string table, object body, string query)
    {
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Patch, $"{_base}/{table}?{query}")
            { Content = JsonContent.Create(body) };
            using var r = await _http.SendAsync(req);
            return (int)r.StatusCode is 200 or 204;
        }
        catch { return false; }
    }

    private async Task<bool> PostAsync(string table, object body)
    {
        try
        {
            using var r = await _http.PostAsJsonAsync($"{_base}/{table}", body);
            return (int)r.StatusCode is 200 or 201;
        }
        catch { return false; }
    }

    // ---------------------------------------------------------------- local file

    private LocalLicense? LoadLocal()
    {
        try
        {
            if (!File.Exists(Paths.License)) return null;
            using var doc = JsonDocument.Parse(File.ReadAllText(Paths.License));
            var e = doc.RootElement;
            string? S(string k) => e.TryGetProperty(k, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;
            var lic = new LocalLicense(S("license_key"), S("agent_name"), S("expires_at"), S("hwid"));
            return lic.Hwid == Hwid ? lic : null;
        }
        catch { return null; }
    }

    private void SaveLocal(string? key, string? agent, string? expiresAt)
    {
        try
        {
            File.WriteAllText(Paths.License, JsonSerializer.Serialize(new
            {
                license_key = key,
                agent_name = agent,
                expires_at = expiresAt,
                hwid = Hwid,
                saved_at = DateTime.Now.ToString("o"),
            }));
        }
        catch { }
    }

    private void DeleteLocal()
    {
        try { if (File.Exists(Paths.License)) { File.Delete(Paths.License); Log.Line("Local license data deleted"); } }
        catch (Exception e) { Log.Line($"Error deleting local license: {e.Message}"); }
    }

    // ---------------------------------------------------------------- helpers

    private static bool IsExpired(string? expiresAt)
    {
        if (string.IsNullOrWhiteSpace(expiresAt)) return false;
        return DateTimeOffset.TryParse(expiresAt, null, System.Globalization.DateTimeStyles.AssumeUniversal, out var exp)
               && exp < DateTimeOffset.UtcNow;
    }

    private static int? CalcDays(string? expiresAt)
    {
        if (string.IsNullOrWhiteSpace(expiresAt)) return null;
        if (!DateTimeOffset.TryParse(expiresAt, null, System.Globalization.DateTimeStyles.AssumeUniversal, out var exp)) return null;
        return Math.Max(0, (int)(exp - DateTimeOffset.UtcNow).TotalDays);
    }

    private static string? Str(JsonElement e, string k) =>
        e.TryGetProperty(k, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;

    private static bool Bool(JsonElement e, string k) =>
        e.TryGetProperty(k, out var p) && p.ValueKind == JsonValueKind.True;

    private void Apply(string? key, string? agent, string? expiresAt)
    {
        IsLicensed = true;
        LicenseKey = key;
        AgentName = string.IsNullOrWhiteSpace(agent) ? "Agent" : agent;
        DaysLeft = CalcDays(expiresAt);
    }

    /// <summary>Persistent activation: bind this machine to the license instead of locking the user out.</summary>
    private async Task<bool> RebindHwidAsync(string licenseKey, string previousHwid)
    {
        if (await PatchAsync("licenses", new { hwid = Hwid }, $"license_key=eq.{licenseKey}"))
        {
            Log.Line($"HWID re-bound for {licenseKey}: {(previousHwid.Length == 0 ? "(empty)" : previousHwid)} -> {Hwid}");
            await RecordDeviceAsync(licenseKey);
            return true;
        }
        Log.Line($"HWID re-bind FAILED for {licenseKey} (server refused)");
        return false;
    }

    /// <summary>Audit trail so the manager can spot a key used on many devices.</summary>
    private Task RecordDeviceAsync(string licenseKey) =>
        PostAsync("device_activations", new { license_key = licenseKey, hardware_id = Hwid, device_name = Environment.MachineName });

    // ---------------------------------------------------------------- license

    /// <summary>
    /// Only two things stop the app: the admin deactivated the key, or it really
    /// expired. A HWID change just re-binds silently. A network error never deletes
    /// anything; the cached activation is trusted until its real expiry.
    /// </summary>
    public async Task<(bool ok, string message)> CheckLicenseAsync()
    {
        var local = LoadLocal();

        if (local != null)
        {
            if (IsExpired(local.ExpiresAt)) return (false, "Expired");

            var key = local.LicenseKey ?? "";
            var (ok, rows) = await FetchAsync("licenses", $"license_key=eq.{key}&select=*");

            if (!ok)
            {
                Log.Line("License server unreachable, using offline grace");
                Apply(local.LicenseKey, local.AgentName, local.ExpiresAt);
                return (true, AgentName);
            }

            if (rows.Length > 0)
            {
                var lic = rows[0];
                if (!Bool(lic, "is_active"))
                {
                    Log.Line($"License {key} deactivated by admin");
                    DeleteLocal();
                    return (false, "Deactivated");
                }
                var expiresAt = Str(lic, "expires_at");
                if (IsExpired(expiresAt)) return (false, "Expired");

                var serverHwid = (Str(lic, "hwid") ?? "").Trim();
                if (serverHwid != Hwid) await RebindHwidAsync(key, serverHwid);

                Apply(Str(lic, "license_key"), Str(lic, "customer_name"), expiresAt);
                SaveLocal(LicenseKey, AgentName, expiresAt);
                return (true, AgentName);
            }
            // Reachable but key not found (deleted): fall through to HWID lookup
        }

        var candidates = string.Join(",", HwidCandidates);
        var (ok2, rows2) = await FetchAsync("licenses", $"hwid=in.({candidates})&select=*");

        if (!ok2)
        {
            if (local != null && !IsExpired(local.ExpiresAt))
            {
                Apply(local.LicenseKey, local.AgentName, local.ExpiresAt);
                return (true, AgentName);
            }
            return (false, "Offline");
        }

        if (rows2.Length > 0)
        {
            var lic = rows2[0];
            if (!Bool(lic, "is_active")) return (false, "Deactivated");
            var expiresAt = Str(lic, "expires_at");
            if (IsExpired(expiresAt)) return (false, "Expired");
            var key = Str(lic, "license_key") ?? "";
            if ((Str(lic, "hwid") ?? "").Trim() != Hwid)
                await PatchAsync("licenses", new { hwid = Hwid }, $"license_key=eq.{key}");
            Apply(key, Str(lic, "customer_name"), expiresAt);
            SaveLocal(LicenseKey, AgentName, expiresAt);
            return (true, AgentName);
        }

        return (false, "Missing");
    }

    /// <summary>An active, unexpired key always activates on the machine in front of us.</summary>
    public async Task<(bool ok, string message)> ActivateLicenseAsync(string licenseKey)
    {
        try
        {
            licenseKey = licenseKey.Trim().ToUpperInvariant();
            var (ok, rows) = await FetchAsync("licenses", $"license_key=eq.{licenseKey}&select=*");
            if (!ok) return (false, "Connection error");
            if (rows.Length == 0) return (false, "Invalid license");

            var lic = rows[0];
            if (!Bool(lic, "is_active")) return (false, "Expired");
            var expiresAt = Str(lic, "expires_at");
            if (IsExpired(expiresAt)) return (false, "Expired");

            var existing = (Str(lic, "hwid") ?? "").Trim();
            if (existing != Hwid && !await RebindHwidAsync(licenseKey, existing))
                return (false, "Registration failed");

            Apply(licenseKey, Str(lic, "customer_name"), expiresAt);
            SaveLocal(LicenseKey, AgentName, expiresAt);
            return (true, AgentName);
        }
        catch { return (false, "Connection error"); }
    }

    // ---------------------------------------------------------------- config + logs

    public async Task<JsonElement?> LoadRemoteConfigAsync()
    {
        if (!IsLicensed) return null;
        var (ok, rows) = await FetchAsync("configurations", $"hardware_id=eq.{Hwid}");
        return ok && rows.Length > 0 ? rows[0] : null;
    }

    public async Task<bool> SaveRemoteConfigAsync(Dictionary<string, object?> row)
    {
        if (!IsLicensed) return false;
        var (ok, rows) = await FetchAsync("configurations", $"hardware_id=eq.{Hwid}");
        bool saved = ok && rows.Length > 0
            ? await PatchAsync("configurations", row, $"hardware_id=eq.{Hwid}")
            : await PostAsync("configurations", row);
        if (!saved) Log.Line("Config save to server FAILED (local copy kept)");
        return saved;
    }

    public Task LogCheckAsync(string? ip, IpLocation? ipLoc, GeoLocation? gpsLoc, string status, string message) =>
        PostAsync("check_logs", new
        {
            hwid = Hwid,
            license_key = LicenseKey,
            ip_address = ip,
            ip_country = ipLoc?.Country,
            ip_state = ipLoc?.State,
            ip_city = ipLoc?.City,
            gps_country = gpsLoc?.Country,
            gps_state = gpsLoc?.State,
            gps_city = gpsLoc?.City,
            status,
            message,
        });
}
