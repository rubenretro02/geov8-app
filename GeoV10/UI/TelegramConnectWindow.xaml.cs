using System.Diagnostics;
using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;
using GeoV10.Core;

namespace GeoV10.UI;

public partial class TelegramConnectWindow : Window
{
    private readonly string _hwid;
    private string? _link;
    private string? _linkId;
    private readonly DispatcherTimer _poll = new() { Interval = TimeSpan.FromSeconds(3) };

    public bool Connected { get; private set; }

    public TelegramConnectWindow(string hwid)
    {
        InitializeComponent();
        _hwid = hwid;
        _poll.Tick += async (_, _) => await PollAsync();
        Loaded += async (_, _) => await GenerateAsync();
    }

    private async Task GenerateAsync()
    {
        var link = await Telegram.GenerateLinkCodeAsync(_hwid);
        if (link == null)
        {
            StatusText.Text = "Could not generate link. Close and try again.";
            StatusText.Foreground = (Brush)FindResource("Error");
            return;
        }
        _link = link.Link;
        _linkId = link.LinkId;
        LinkBox.Text = link.Link;
        StatusText.Text = "Waiting for you to press Start in Telegram...";
        _poll.Start();
    }

    private async Task PollAsync()
    {
        if (_linkId == null) return;
        var status = await Telegram.CheckLinkStatusAsync(_linkId);
        if (status == "connected")
        {
            _poll.Stop();
            Connected = true;
            StatusText.Text = "✓ Connected!";
            StatusText.Foreground = (Brush)FindResource("Success");
            await Task.Delay(1200);
            Close();
        }
        else if (status == "expired")
        {
            _poll.Stop();
            StatusText.Text = "Code expired. Close and try again.";
            StatusText.Foreground = (Brush)FindResource("Error");
        }
    }

    private void Copy_Click(object sender, RoutedEventArgs e)
    {
        if (_link is { Length: > 0 }) { try { Clipboard.SetText(_link); CopyBtn.Content = "✓ Copied"; } catch { } }
    }

    private void Open_Click(object sender, RoutedEventArgs e)
    {
        if (_link is { Length: > 0 })
            try { Process.Start(new ProcessStartInfo(_link) { UseShellExecute = true }); } catch (Exception ex) { Log.Line($"open telegram: {ex.Message}"); }
    }

    private void Close_Click(object sender, RoutedEventArgs e) { _poll.Stop(); Close(); }
}
