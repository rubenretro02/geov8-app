using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;

namespace GeoV10.Core;

/// <summary>
/// Windows Device Portal location override (http://localhost:50080). Pure HTTP,
/// exactly the endpoints and status handling of the Python app.
/// </summary>
public sealed class DevicePortal
{
    private readonly HttpClient _http;
    public string BaseUri { get; } = $"http://localhost:{AppInfo.DevicePortalPort}";

    public DevicePortal(string username, string password)
    {
        _http = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        var token = Convert.ToBase64String(Encoding.UTF8.GetBytes($"{username}:{password}"));
        _http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Basic", token);
    }

    public async Task<(bool ok, string error)> TestAsync()
    {
        try
        {
            using var r = await _http.GetAsync($"{BaseUri}/api/os/info");
            return (int)r.StatusCode switch
            {
                401 => (false, "auth_failed"),
                200 => (true, "ok"),
                _ => (false, "unavailable"),
            };
        }
        catch (HttpRequestException) { return (false, "connection_failed"); }
        catch (Exception e) { return (false, e.Message); }
    }

    public async Task InitializeLocationAsync()
    {
        foreach (var ep in new[] { "/ext/location", "/ext/location/override", "/ext/location/position" })
        {
            try { using var _ = await _http.GetAsync(BaseUri + ep); } catch { }
        }
        await Task.Delay(1000);
    }

    public async Task<(bool ok, string error)> SetPositionAsync(double lat, double lon)
    {
        try
        {
            using var r1 = await _http.PutAsJsonAsync($"{BaseUri}/ext/location/override", new { Override = true });
            Log.Line($"Override response: {(int)r1.StatusCode}");
            if ((int)r1.StatusCode == 401) return (false, "auth_failed");
            if ((int)r1.StatusCode is not (200 or 204)) return (false, "override_failed");

            using var r2 = await _http.PutAsJsonAsync($"{BaseUri}/ext/location/position",
                new { Latitude = lat, Longitude = lon, Altitude = 0 });
            Log.Line($"Position response: {(int)r2.StatusCode}");
            if ((int)r2.StatusCode == 401) return (false, "auth_failed");
            if ((int)r2.StatusCode is not (200 or 204)) return (false, "position_failed");

            return (true, "ok");
        }
        catch (HttpRequestException) { return (false, "connection_failed"); }
        catch (Exception e)
        {
            Log.Line($"set_position error: {e.Message}");
            return (false, e.Message);
        }
    }

    /// <summary>Latitude read back from the portal, or null if unavailable.</summary>
    public async Task<double?> GetPositionLatitudeAsync()
    {
        try
        {
            using var r = await _http.GetAsync($"{BaseUri}/ext/location/position");
            if ((int)r.StatusCode != 200) return null;
            using var doc = JsonDocument.Parse(await r.Content.ReadAsStringAsync());
            if (doc.RootElement.TryGetProperty("Latitude", out var p) && p.TryGetDouble(out var lat)) return lat;
            return 0;
        }
        catch { return null; }
    }
}
