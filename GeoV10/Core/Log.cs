using System.Diagnostics;
using System.IO;

namespace GeoV10.Core;

/// <summary>Diagnostic log at %APPDATA%\GeoV8\geo.log (same file the Python app writes).</summary>
public static class Log
{
    private static readonly object Gate = new();

    public static void Line(string message)
    {
        var stamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
        Debug.WriteLine(message);
        try
        {
            lock (Gate)
            {
                var fi = new FileInfo(Paths.Log);
                if (fi.Exists && fi.Length > 512 * 1024)
                {
                    var text = File.ReadAllText(Paths.Log);
                    File.WriteAllText(Paths.Log, text[^Math.Min(100_000, text.Length)..]);
                }
                File.AppendAllText(Paths.Log, $"[{stamp}] {message}{Environment.NewLine}");
            }
        }
        catch { /* never let logging break the app */ }
    }
}
