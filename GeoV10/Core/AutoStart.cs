using System.Diagnostics;
using System.IO;
using Microsoft.Win32;

namespace GeoV10.Core;

/// <summary>
/// Windows auto-start. Two mechanisms, same as the Python app:
///  - a Registry Run entry (fallback), refreshed when it points at an old exe;
///  - a Scheduled Task with an "At log on" trigger, which is NOT throttled by
///    Explorer after logon (that throttle was the ~10 min boot delay on VMs).
/// The single-instance guard prevents both from launching a duplicate.
/// </summary>
public static class AutoStart
{
    private const string RunKeyPath = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string RunValueName = "GeoApp";
    private const string TaskName = "GeoAppLogon";

    public static bool LaunchedByAutostart =>
        Environment.GetCommandLineArgs().Any(a => a.Equals("--autostart", StringComparison.OrdinalIgnoreCase));

    /// <summary>Minutes since the machine booted (GetTickCount64).</summary>
    public static double UptimeMinutes => Environment.TickCount64 / 60000.0;

    public static bool IsSystemJustBooted(double maxMinutes = 5) => UptimeMinutes <= maxMinutes;

    private static string ExePath => Environment.ProcessPath ?? "";

    public static void Ensure()
    {
        try
        {
            RemoveRunKeyStartupDelay();
            EnsureRegistry();
            EnsureScheduledTask();
        }
        catch (Exception e) { Log.Line($"AutoStart.Ensure error: {e.Message}"); }
    }

    /// <summary>
    /// Explorer delays Run-key startup apps after logon (StartupDelayInMSec,
    /// ~10s+ by default). Setting it to 0 - a per-user, non-admin write - makes
    /// the Run-key launch fire immediately. The Scheduled Task (when it can be
    /// created, which needs admin) is still faster/earlier, but this helps the
    /// common non-elevated case.
    /// </summary>
    private static void RemoveRunKeyStartupDelay()
    {
        try
        {
            using var key = Registry.CurrentUser.CreateSubKey(
                @"Software\Microsoft\Windows\CurrentVersion\Explorer\Serialize");
            key?.SetValue("StartupDelayInMSec", 0, RegistryValueKind.DWord);
        }
        catch (Exception e) { Log.Line($"RemoveRunKeyStartupDelay error: {e.Message}"); }
    }

    private static void EnsureRegistry()
    {
        try
        {
            var want = $"\"{ExePath}\" --autostart";
            using var key = Registry.CurrentUser.OpenSubKey(RunKeyPath, writable: true)
                            ?? Registry.CurrentUser.CreateSubKey(RunKeyPath);
            var current = key?.GetValue(RunValueName) as string;
            if (!string.Equals(current, want, StringComparison.OrdinalIgnoreCase))
            {
                key?.SetValue(RunValueName, want, RegistryValueKind.String);
                Log.Line($"Registry Run entry set: {want}");
            }
        }
        catch (Exception e) { Log.Line($"EnsureRegistry error: {e.Message}"); }
    }

    private static void EnsureScheduledTask()
    {
        try
        {
            if (ScheduledTaskIsCurrent()) return;

            var xml = $@"<?xml version=""1.0"" encoding=""UTF-16""?>
<Task version=""1.2"" xmlns=""http://schemas.microsoft.com/windows/2004/02/mit/task"">
  <RegistrationInfo><Description>Geo auto-start</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
  <Principals><Principal id=""Author""><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context=""Author""><Exec><Command>""{ExePath}""</Command><Arguments>--autostart</Arguments></Exec></Actions>
</Task>";
            File.WriteAllText(Paths.TaskXml, xml, System.Text.Encoding.Unicode);
            var r = RunSchtasks($"/Create /TN {TaskName} /XML \"{Paths.TaskXml}\" /F");
            try { File.Delete(Paths.TaskXml); } catch { }
            Log.Line(r.ok ? $"Scheduled task '{TaskName}' registered (fast startup)"
                          : $"Scheduled task registration failed: {r.output}");
        }
        catch (Exception e) { Log.Line($"EnsureScheduledTask error: {e.Message}"); }
    }

    private static bool ScheduledTaskIsCurrent()
    {
        var r = RunSchtasks($"/Query /TN {TaskName} /XML");
        return r.ok && r.output.Contains(ExePath, StringComparison.OrdinalIgnoreCase);
    }

    private static (bool ok, string output) RunSchtasks(string args)
    {
        try
        {
            var psi = new ProcessStartInfo("schtasks.exe", args)
            {
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true,
            };
            using var p = Process.Start(psi)!;
            var outp = p.StandardOutput.ReadToEnd() + p.StandardError.ReadToEnd();
            p.WaitForExit(15000);
            return (p.ExitCode == 0, outp);
        }
        catch (Exception e) { return (false, e.Message); }
    }
}
