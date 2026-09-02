using System.IO;

namespace GeoV10.Core;

/// <summary>
/// Same folder and file names as the Python app (%APPDATA%\GeoV8), so a machine
/// that upgrades keeps its license, frozen HWID and settings without doing anything.
/// </summary>
public static class Paths
{
    public static readonly string AppData =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "GeoV8");

    static Paths()
    {
        try { Directory.CreateDirectory(AppData); } catch { /* fall through; writes will fail softly */ }
    }

    public static string License => Path.Combine(AppData, "license_data.json");
    public static string Config => Path.Combine(AppData, "config_local.json");
    public static string HwidCache => Path.Combine(AppData, "hwid_cache.json");
    public static string Log => Path.Combine(AppData, "geo.log");
    public static string WebView2Data => Path.Combine(AppData, "webview2");
}
