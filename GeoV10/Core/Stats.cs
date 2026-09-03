using System.IO;
using System.Text.Json;

namespace GeoV10.Core;

/// <summary>Check counters in stats.json (same file as the Python StatsManager).</summary>
public static class Stats
{
    public static void Record(bool success)
    {
        try
        {
            var data = Load();
            data["total"] = GetInt(data, "total") + 1;
            data[success ? "success" : "fail"] = GetInt(data, success ? "success" : "fail") + 1;
            data["last_check"] = DateTime.Now.ToString("o");
            File.WriteAllText(Paths.Stats, JsonSerializer.Serialize(data));
        }
        catch (Exception e) { Log.Line($"Stats.Record error: {e.Message}"); }
    }

    private static Dictionary<string, object> Load()
    {
        try
        {
            if (File.Exists(Paths.Stats))
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(Paths.Stats));
                var d = new Dictionary<string, object>();
                foreach (var p in doc.RootElement.EnumerateObject())
                    d[p.Name] = p.Value.ValueKind == JsonValueKind.Number ? p.Value.GetInt32() : (object)(p.Value.GetString() ?? "");
                return d;
            }
        }
        catch { }
        return new Dictionary<string, object>();
    }

    private static int GetInt(Dictionary<string, object> d, string k) =>
        d.TryGetValue(k, out var v) && v is int i ? i : 0;
}
