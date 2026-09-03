using System.Drawing;
using System.Windows.Forms;
using GeoV10.Core;

namespace GeoV10.UI;

/// <summary>
/// System-tray icon: balloon notifications (the Python winotify toasts) plus a
/// right-click menu to Show/Exit - important now that the app runs hidden in the
/// background, so there is always a way back to the window without Task Manager.
/// </summary>
public sealed class TrayIcon : IDisposable
{
    private readonly NotifyIcon _icon;

    public TrayIcon(Action onShow, Action onExit)
    {
        Icon ico;
        try { ico = Icon.ExtractAssociatedIcon(Environment.ProcessPath!) ?? SystemIcons.Application; }
        catch { ico = SystemIcons.Application; }

        var menu = new ContextMenuStrip();
        menu.Items.Add("Show", null, (_, _) => onShow());
        menu.Items.Add("Exit", null, (_, _) => onExit());

        _icon = new NotifyIcon
        {
            Icon = ico,
            Text = "Geo",
            Visible = true,
            ContextMenuStrip = menu,
        };
        _icon.DoubleClick += (_, _) => onShow();
    }

    public void Notify(string title, string message, bool success)
    {
        try
        {
            _icon.BalloonTipIcon = success ? ToolTipIcon.Info : ToolTipIcon.Warning;
            _icon.BalloonTipTitle = title;
            _icon.BalloonTipText = message;
            _icon.ShowBalloonTip(4000);
        }
        catch (Exception e) { Log.Line($"Tray notify error: {e.Message}"); }
    }

    public void Dispose()
    {
        try { _icon.Visible = false; _icon.Dispose(); } catch { }
    }
}
