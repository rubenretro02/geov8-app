using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;

namespace GeoV10.Core;

public sealed record TelegramLink(string Code, string Link, string LinkId, string? ExpiresAt);
public sealed record TelegramAccount(string ChatId, string Name);

/// <summary>
/// Telegram alerts via the License Manager API - a 1:1 port of the Python
/// send_telegram_alert / generate_telegram_link_code / status / list / remove.
/// The API filters for agent and admin independently, so we always POST.
/// </summary>
public static class Telegram
{
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(10) };
    private static string Api => AppInfo.LicenseManagerUrl;

    public static async Task<bool> SendAlertAsync(string? licenseKey, string status, string? ip, string location,
        string message, string chatIds, string? errorType,
        bool alertIp, bool alertGps, bool alertOnFail, bool alertOnSuccess)
    {
        try
        {
            using var r = await Http.PostAsJsonAsync($"{Api}/api/notify", new
            {
                license_key = licenseKey,
                status,
                ip = ip ?? "unknown",
                location,
                message,
                chat_ids = chatIds,
                error_type = errorType,
                agent_alert_ip = alertIp,
                agent_alert_gps = alertGps,
                agent_alert_on_fail = alertOnFail,
                agent_alert_on_success = alertOnSuccess,
            });
            Log.Line($"[Telegram] notify status={status} -> HTTP {(int)r.StatusCode}");
            return r.IsSuccessStatusCode;
        }
        catch (Exception e) { Log.Line($"[Telegram] notify failed: {e.Message}"); return false; }
    }

    public static async Task<TelegramLink?> GenerateLinkCodeAsync(string hardwareId)
    {
        try
        {
            using var r = await Http.PostAsJsonAsync($"{Api}/api/telegram/generate-code", new { hardware_id = hardwareId });
            if (!r.IsSuccessStatusCode) return null;
            using var doc = JsonDocument.Parse(await r.Content.ReadAsStringAsync());
            var d = doc.RootElement;
            if (!(d.TryGetProperty("success", out var s) && s.ValueKind == JsonValueKind.True)) return null;
            return new TelegramLink(Str(d, "code") ?? "", Str(d, "link") ?? "", Str(d, "link_id") ?? "", Str(d, "expires_at"));
        }
        catch (Exception e) { Log.Line($"[Telegram] generate-code failed: {e.Message}"); return null; }
    }

    /// <summary>"pending" | "connected" | "expired".</summary>
    public static async Task<string> CheckLinkStatusAsync(string linkId)
    {
        try
        {
            using var r = await Http.GetAsync($"{Api}/api/telegram/status?link_id={linkId}");
            if (!r.IsSuccessStatusCode) return "pending";
            using var doc = JsonDocument.Parse(await r.Content.ReadAsStringAsync());
            return Str(doc.RootElement, "status") ?? "pending";
        }
        catch { return "pending"; }
    }

    public static async Task<List<TelegramAccount>> ListConnectedAsync(string hardwareId)
    {
        var list = new List<TelegramAccount>();
        try
        {
            using var r = await Http.GetAsync($"{Api}/api/telegram/list?hardware_id={hardwareId}");
            if (!r.IsSuccessStatusCode) return list;
            using var doc = JsonDocument.Parse(await r.Content.ReadAsStringAsync());
            if (doc.RootElement.TryGetProperty("accounts", out var arr) && arr.ValueKind == JsonValueKind.Array)
                foreach (var a in arr.EnumerateArray())
                    list.Add(new TelegramAccount(Str(a, "chat_id") ?? "", Str(a, "name") ?? Str(a, "username") ?? "Telegram"));
        }
        catch (Exception e) { Log.Line($"[Telegram] list failed: {e.Message}"); }
        return list;
    }

    public static async Task<bool> RemoveAsync(string hardwareId, string chatId)
    {
        try
        {
            using var r = await Http.PostAsJsonAsync($"{Api}/api/telegram/remove", new { hardware_id = hardwareId, chat_id = chatId });
            return r.IsSuccessStatusCode;
        }
        catch { return false; }
    }

    private static string? Str(JsonElement e, string k) =>
        e.TryGetProperty(k, out var p) && p.ValueKind == JsonValueKind.String ? p.GetString() : null;
}
