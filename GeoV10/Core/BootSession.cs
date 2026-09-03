using System.IO;
using System.Text.Json;

namespace GeoV10.Core;

/// <summary>
/// Robust "is this the first launch since the machine booted?" detection, so the
/// boot auto-check and hidden-at-boot behaviour no longer depend on the fragile
/// "--autostart arrived" signal (a stale Run-key entry, a Defender-removed key,
/// or a moved exe used to break it - the UI would show and no check ran).
///
/// The boot time is derived from uptime (now - TickCount64) and rounded; the
/// first launch that sees a new boot time claims it in boot_session.json. Later
/// manual re-opens within the same boot see the same value and do NOT re-run the
/// check (that was the "phantom check on manual open" complaint).
/// </summary>
public static class BootSession
{
    /// <summary>True exactly once per OS boot: the first Geo launch of this boot.</summary>
    public static bool IsFirstLaunchThisBoot()
    {
        try
        {
            var bootId = DateTimeOffset.UtcNow.AddMilliseconds(-Environment.TickCount64)
                .ToUnixTimeSeconds() / 60;   // minute-rounded boot time
            var last = Load();
            if (last == bootId) return false;
            File.WriteAllText(Paths.BootMarker, JsonSerializer.Serialize(new { boot_id = bootId }));
            return true;
        }
        catch (Exception e)
        {
            Log.Line($"BootSession error: {e.Message}");
            return false;
        }
    }

    private static long Load()
    {
        try
        {
            if (File.Exists(Paths.BootMarker))
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(Paths.BootMarker));
                if (doc.RootElement.TryGetProperty("boot_id", out var p) && p.TryGetInt64(out var v)) return v;
            }
        }
        catch { }
        return -1;
    }
}
