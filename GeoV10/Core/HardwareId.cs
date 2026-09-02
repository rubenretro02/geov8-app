using System.Management;
using System.Net.NetworkInformation;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.IO;

namespace GeoV10.Core;

public sealed record HardwareInfo(string Primary, IReadOnlyList<string> Candidates);

/// <summary>
/// Port of get_hardware_info() from the Python app. The hash formula is IDENTICAL
/// (sha256 of "bios-baseboard-uuid", first 32 hex chars, upper-case) so bindings
/// made by the Python app are recognised, and the frozen HWID is read from the
/// same hwid_cache.json.
/// </summary>
public static class HardwareId
{
    private static readonly HashSet<string> Junk = new(StringComparer.OrdinalIgnoreCase)
    {
        "", "none", "null", "0", "00000000", "default string",
        "to be filled by o.e.m.", "to be filled by oem", "system serial number",
        "not applicable", "not specified", "invalid", "unknown", "n/a",
        "oem", "chassis serial number", "base board serial number",
    };

    public static HardwareInfo Get()
    {
        var rawBios = Wmi("Win32_BIOS", "SerialNumber");
        var rawBoard = Wmi("Win32_BaseBoard", "SerialNumber");
        var rawUuid = Wmi("Win32_ComputerSystemProduct", "UUID");

        var bios = Clean(rawBios);
        var board = Clean(rawBoard);
        var uid = Clean(rawUuid);

        var candidates = new HashSet<string>();

        // Fuzzy combos: each cleaned field either present or blank
        foreach (var b in new[] { bios, "" }.Distinct())
        foreach (var m in new[] { board, "" }.Distinct())
        foreach (var u in new[] { uid, "" }.Distinct())
            if (b.Length > 0 || m.Length > 0 || u.Length > 0)
                candidates.Add(Hash(b, m, u));

        // Legacy: exactly how the original code hashed the raw values
        if (rawBios.Length > 0 || rawBoard.Length > 0 || rawUuid.Length > 0)
            candidates.Add(Hash(rawBios, rawBoard, rawUuid));

        string? fallback = null;
        if (bios.Length == 0 && board.Length == 0 && uid.Length == 0)
        {
            fallback = FallbackHash();
            if (fallback != null)
            {
                candidates.Add(fallback);
                Log.Line("[HWID] WARNING: All WMI blank, using fallback (MAC+processor)");
            }
        }

        var cached = LoadCached();
        string primary;
        if (cached != null)
        {
            primary = cached; // frozen - never flips once set
        }
        else
        {
            primary = (bios.Length > 0 || board.Length > 0 || uid.Length > 0)
                ? Hash(bios, board, uid)
                : fallback ?? Hash("", "", "");
            SaveCached(primary);
            Log.Line($"[HWID] Frozen new HWID: {primary} (bios={bios.Length > 0} board={board.Length > 0} uuid={uid.Length > 0})");
        }

        candidates.Add(primary);
        var list = candidates.OrderBy(c => c, StringComparer.Ordinal).ToList();
        Log.Line($"[HWID] Primary: {primary} ({list.Count} candidates)");
        return new HardwareInfo(primary, list);
    }

    private static string Wmi(string cls, string prop, int maxRetries = 3, int retryDelayMs = 2000)
    {
        for (var attempt = 0; attempt < maxRetries; attempt++)
        {
            try
            {
                using var searcher = new ManagementObjectSearcher($"SELECT {prop} FROM {cls}");
                foreach (var o in searcher.Get())
                {
                    var v = o[prop]?.ToString()?.Trim() ?? "";
                    if (v.Length > 0)
                    {
                        Log.Line($"[HWID] {cls}.{prop}: OK");
                        return v;
                    }
                }
                if (attempt < maxRetries - 1)
                {
                    Log.Line($"[HWID] {cls}.{prop}: empty, retry {attempt + 2}/{maxRetries}");
                    Thread.Sleep(retryDelayMs);
                }
            }
            catch (Exception e)
            {
                Log.Line($"[HWID] {cls}.{prop}: error ({e.Message})");
                if (attempt < maxRetries - 1) Thread.Sleep(retryDelayMs);
            }
        }
        Log.Line($"[HWID] {cls}.{prop}: FAILED after {maxRetries} attempts");
        return "";
    }

    /// <summary>Collapse whitespace; placeholder/junk serials become blank.</summary>
    private static string Clean(string v)
    {
        if (string.IsNullOrEmpty(v)) return "";
        var collapsed = string.Join(" ", v.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries)).Trim();
        return Junk.Contains(collapsed) ? "" : collapsed;
    }

    /// <summary>CRITICAL: same format as the Python app for compatibility.</summary>
    private static string Hash(string bios, string board, string uuid)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes($"{bios}-{board}-{uuid}"));
        return Convert.ToHexString(bytes)[..32].ToUpperInvariant();
    }

    private static string? FallbackHash()
    {
        try
        {
            var nic = NetworkInterface.GetAllNetworkInterfaces()
                .FirstOrDefault(n => n.NetworkInterfaceType != NetworkInterfaceType.Loopback
                                     && n.GetPhysicalAddress().GetAddressBytes().Length == 6);
            long mac = 0;
            if (nic != null)
                foreach (var b in nic.GetPhysicalAddress().GetAddressBytes()) mac = (mac << 8) | b;
            var processor = Environment.GetEnvironmentVariable("PROCESSOR_IDENTIFIER") ?? "";
            var bytes = SHA256.HashData(Encoding.UTF8.GetBytes($"{mac}-{processor}"));
            return Convert.ToHexString(bytes)[..32].ToUpperInvariant();
        }
        catch { return null; }
    }

    private static string? LoadCached()
    {
        try
        {
            if (!File.Exists(Paths.HwidCache)) return null;
            using var doc = JsonDocument.Parse(File.ReadAllText(Paths.HwidCache));
            var v = doc.RootElement.TryGetProperty("hwid", out var p) ? p.GetString()?.Trim() : null;
            return string.IsNullOrEmpty(v) ? null : v;
        }
        catch { return null; }
    }

    private static void SaveCached(string hwid)
    {
        try { File.WriteAllText(Paths.HwidCache, JsonSerializer.Serialize(new { hwid })); }
        catch { }
    }
}
