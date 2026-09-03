using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace GeoV10.Core;

/// <summary>
/// Self-update, same model as the Python AutoUpdater: read the latest row from
/// the Supabase `app_version` table, compare versions, download the exe, then a
/// .bat kills this process, replaces the exe in place, rewrites the Run key with
/// --autostart and relaunches. This is also what carries future C# updates after
/// the one-time Python-&gt;C# migration (which the Python updater performs by
/// pointing app_version at this exe).
/// </summary>
public static class Updater
{
    public static async Task<bool> CheckAndApplyAsync(bool relaunchWithAutostart)
    {
        try
        {
            using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
            http.DefaultRequestHeaders.Add("apikey", AppInfo.SupabaseKey);
            http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue("Bearer", AppInfo.SupabaseKey);

            var url = $"{AppInfo.SupabaseUrl}/rest/v1/app_version?select=*&order=created_at.desc&limit=1";
            var rows = await http.GetFromJsonSafeAsync(url);
            if (rows == null || rows.Value.GetArrayLength() == 0) return false;

            var latest = rows.Value[0];
            var version = Str(latest, "version") ?? "0";
            var downloadUrl = Str(latest, "download_url") ?? "";
            if (downloadUrl.Length == 0 || CompareVersions(version, AppInfo.Version) <= 0) return false;

            Log.Line($"Update available: {version} (current {AppInfo.Version})");
            return await DownloadAndApplyAsync(downloadUrl, relaunchWithAutostart);
        }
        catch (Exception e)
        {
            Log.Line($"Update check error: {e.Message}");
            return false;
        }
    }

    private static async Task<bool> DownloadAndApplyAsync(string downloadUrl, bool relaunchWithAutostart)
    {
        try
        {
            Directory.CreateDirectory(Paths.UpdateDir);
            var newExe = Path.Combine(Paths.UpdateDir, "app_new.exe");

            using (var http = new HttpClient { Timeout = TimeSpan.FromMinutes(5) })
            using (var resp = await http.GetAsync(downloadUrl, HttpCompletionOption.ResponseHeadersRead))
            {
                if (!resp.IsSuccessStatusCode) { Log.Line($"Download failed HTTP {(int)resp.StatusCode}"); return false; }
                await using var src = await resp.Content.ReadAsStreamAsync();
                await using var dst = File.Create(newExe);
                await src.CopyToAsync(dst);
            }
            if (new FileInfo(newExe).Length < 100_000) { Log.Line("Downloaded file too small"); return false; }

            var currentExe = Environment.ProcessPath!;
            var pid = Environment.ProcessId;
            var runVal = $"\\\"{currentExe}\\\"" + (relaunchWithAutostart ? " --autostart" : "");
            var relaunchArgs = relaunchWithAutostart ? " --autostart" : "";
            var bat = Path.Combine(Paths.UpdateDir, "geo_updater.bat");

            var sb = new StringBuilder();
            sb.AppendLine("@echo off");
            sb.AppendLine($"taskkill /PID {pid} /F >nul 2>&1");
            sb.AppendLine("taskkill /IM \"app.exe\" /F >nul 2>&1");
            sb.AppendLine("timeout /t 3 /nobreak >nul");
            sb.AppendLine($"copy /y \"{newExe}\" \"{currentExe}\" >nul 2>&1");
            sb.AppendLine($"reg add \"HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\" /v \"GeoApp\" /t REG_SZ /d \"{runVal}\" /f >nul 2>&1");
            sb.AppendLine($"start \"\" \"{currentExe}\"{relaunchArgs}");
            sb.AppendLine("timeout /t 2 /nobreak >nul");
            sb.AppendLine($"del /f /q \"{newExe}\" >nul 2>&1");
            sb.AppendLine($"(goto) 2>nul & del /f /q \"{bat}\"");   // self-delete
            File.WriteAllText(bat, sb.ToString(), new UTF8Encoding(false));

            Log.Line($"Launching updater to install over {currentExe}");
            Process.Start(new ProcessStartInfo("cmd.exe", $"/c \"{bat}\"")
            {
                CreateNoWindow = true,
                UseShellExecute = false,
                WindowStyle = ProcessWindowStyle.Hidden,
            });
            return true;
        }
        catch (Exception e)
        {
            Log.Line($"DownloadAndApply error: {e.Message}");
            return false;
        }
    }

    /// <summary>1 if a&gt;b, -1 if a&lt;b, 0 equal. Same numeric-dotted rule as the Python app.</summary>
    public static int CompareVersions(string a, string b)
    {
        try
        {
            int[] Parse(string v) => v.Replace("v", "").Split('.').Select(x => int.TryParse(x, out var n) ? n : 0).ToArray();
            var pa = Parse(a); var pb = Parse(b);
            for (var i = 0; i < Math.Max(pa.Length, pb.Length); i++)
            {
                var x = i < pa.Length ? pa[i] : 0;
                var y = i < pb.Length ? pb[i] : 0;
                if (x != y) return x > y ? 1 : -1;
            }
            return 0;
        }
        catch { return 0; }
    }

    private static string? Str(JsonElement e, string k) =>
        e.TryGetProperty(k, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;
}

internal static class HttpJsonExtensions
{
    public static async Task<JsonElement?> GetFromJsonSafeAsync(this HttpClient http, string url)
    {
        try
        {
            using var r = await http.GetAsync(url);
            if (!r.IsSuccessStatusCode) return null;
            using var doc = JsonDocument.Parse(await r.Content.ReadAsStringAsync());
            return doc.RootElement.Clone();
        }
        catch { return null; }
    }
}
