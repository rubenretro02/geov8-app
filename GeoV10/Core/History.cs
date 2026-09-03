using System.IO;
using System.Text.Json;

namespace GeoV10.Core;

/// <summary>Rolling check history in history.json (same file as the Python HistoryManager).</summary>
public static class History
{
    private const int MaxEntries = 200;

    public static void Record(string status, string ip, string location, string message)
    {
        try
        {
            var list = Load();
            list.Insert(0, new HistoryEntry(DateTime.Now.ToString("o"), status, ip, location, message));
            if (list.Count > MaxEntries) list = list.GetRange(0, MaxEntries);
            File.WriteAllText(Paths.History, JsonSerializer.Serialize(list));
        }
        catch (Exception e) { Log.Line($"History.Record error: {e.Message}"); }
    }

    private static List<HistoryEntry> Load()
    {
        try
        {
            if (File.Exists(Paths.History))
                return JsonSerializer.Deserialize<List<HistoryEntry>>(File.ReadAllText(Paths.History)) ?? new();
        }
        catch { }
        return new List<HistoryEntry>();
    }
}

public sealed record HistoryEntry(string time, string status, string ip, string location, string message);
