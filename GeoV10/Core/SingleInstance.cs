using System.IO;
using System.Threading;

namespace GeoV10.Core;

/// <summary>
/// One running instance. A second launch drops a flag file asking the running
/// instance (which may be hidden in the background) to show itself, then exits.
/// Same mechanism and flag file as the Python app (show_window.flag).
/// </summary>
public static class SingleInstance
{
    private static Mutex? _mutex;
    private const string MutexName = @"Local\GeoV8App_SingleInstance";

    /// <summary>True if this is the only instance. False (after signalling "show") if another is running.</summary>
    public static bool Acquire()
    {
        try
        {
            _mutex = new Mutex(initiallyOwned: true, MutexName, out var createdNew);
            if (!createdNew)
            {
                Log.Line("Already running - asking the existing window to show");
                try { File.WriteAllText(Paths.ShowFlag, "show"); } catch (Exception e) { Log.Line($"Could not write show flag: {e.Message}"); }
                return false;
            }
            return true;
        }
        catch (Exception e)
        {
            Log.Line($"Single instance check failed ({e.Message}) - continuing");
            return true;
        }
    }

    public static void ClearStaleFlag()
    {
        try { if (File.Exists(Paths.ShowFlag)) File.Delete(Paths.ShowFlag); } catch { }
    }

    /// <summary>True (once) when a second launch asked this instance to show itself.</summary>
    public static bool ConsumeShowRequest()
    {
        try
        {
            if (File.Exists(Paths.ShowFlag)) { File.Delete(Paths.ShowFlag); return true; }
        }
        catch { }
        return false;
    }
}
