using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Input;
using System.Windows.Media;
using GeoV10.Core;

namespace GeoV10.UI;

public partial class LicenseWindow : Window
{
    private readonly LicenseService _license;
    private readonly string? _existingKey;

    public LicenseWindow(LicenseService license, string errorMsg)
    {
        InitializeComponent();
        _license = license;

        // Saved key, shown MASKED so it can't be read and leaked
        try
        {
            if (File.Exists(Paths.License))
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(Paths.License));
                if (doc.RootElement.TryGetProperty("license_key", out var k)) _existingKey = k.GetString();
            }
        }
        catch { }

        Brush B(string key) => (Brush)FindResource(key);
        (string title, string sub, Brush color) = errorMsg switch
        {
            "Expired" => ("⚠️ License Expired", "Contact support to renew", B("Error")),
            "Reset" => ("🔄 License Reset", "Your license was reset by admin", B("Warning")),
            "HWID mismatch" => ("🖥️ Device Changed", "Contact support for HWID reset", B("Error")),
            "Deactivated" => ("🚫 License Deactivated", "Contact support for help", B("Error")),
            "Offline" => ("📡 No Internet Connection", "Connect to the internet to activate, or enter your key", B("Warning")),
            "No license" => ("Enter License Key", "", B("Text")),
            _ => ("License Error", errorMsg, B("Error")),
        };
        TitleText.Text = title; TitleText.Foreground = color;
        SubtitleText.Text = sub;
        SubtitleText.Visibility = string.IsNullOrEmpty(sub) ? Visibility.Collapsed : Visibility.Visible;

        if (!string.IsNullOrEmpty(_existingKey))
        {
            ExistingPanel.Visibility = Visibility.Visible;
            ExistingText.Text = AppInfo.MaskLicense(_existingKey);
        }
        else
        {
            Height = 250;
        }
    }

    private void KeyBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter) Activate_Click(sender, e);
    }

    private async void Activate_Click(object sender, RoutedEventArgs e)
    {
        // Empty box + a saved key = retry with the saved key
        var key = KeyBox.Text.Trim();
        if (key.Length == 0) key = _existingKey ?? "";
        if (key.Length == 0) { StatusText.Text = "Enter license key"; return; }

        ActivateBtn.IsEnabled = false; ActivateBtn.Content = "...";
        StatusText.Text = "";

        var (ok, message) = await _license.ActivateLicenseAsync(key);

        ActivateBtn.IsEnabled = true; ActivateBtn.Content = "Activate";
        if (ok) { DialogResult = true; Close(); }
        else StatusText.Text = message;
    }
}
