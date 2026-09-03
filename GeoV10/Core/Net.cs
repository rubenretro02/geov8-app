using System.Net.Http;

namespace GeoV10.Core;

/// <summary>Internet reachability, with retries for the just-booted case (network up late).</summary>
public static class Net
{
    private static readonly string[] Probes =
    {
        "https://api.ipify.org", "https://www.google.com", "https://www.cloudflare.com",
    };

    public static async Task<bool> HasInternetAsync()
    {
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(5) };
        foreach (var url in Probes)
        {
            try { using var _ = await http.GetAsync(url); return true; } catch { }
        }
        return false;
    }

    /// <summary>Wait for internet, retrying every 5s. Right after boot the network is often not up yet.</summary>
    public static async Task<bool> WaitForInternetAsync(int attempts = 6)
    {
        for (var i = 1; i <= attempts; i++)
        {
            if (await HasInternetAsync()) return true;
            Log.Line($"No internet yet, retry {i}/{attempts} in 5s");
            if (i < attempts) await Task.Delay(5000);
        }
        return false;
    }
}
