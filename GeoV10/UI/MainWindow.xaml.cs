using System.Globalization;
using System.Media;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Threading;
using GeoV10.Core;

namespace GeoV10.UI;

public partial class MainWindow : Window
{
    private readonly LicenseService _license;
    private AppConfig _config = new();
    private readonly CurrentData _data = new();

    private bool _isRunning;
    private bool _currentCheckAuto;

    private readonly DispatcherTimer _autoTimer = new();
    private readonly DispatcherTimer _countdownTimer = new() { Interval = TimeSpan.FromSeconds(1) };
    private readonly DispatcherTimer _dotsTimer = new() { Interval = TimeSpan.FromMilliseconds(300) };
    private DateTime? _nextCheckTime;
    private int _autoInterval = 5;
    private int _dotPhase;

    private Brush B(string key) => (Brush)FindResource(key);

    public MainWindow(LicenseService license)
    {
        InitializeComponent();
        _license = license;
        _autoTimer.Tick += AutoTimer_Tick;
        _countdownTimer.Tick += (_, _) => UpdateCountdown();
        _dotsTimer.Tick += (_, _) => { _dotPhase = (_dotPhase + 1) % 4; RunBtn.Content = new string('●', _dotPhase) + new string('○', 3 - _dotPhase); };
        VersionLabel.Text = $"v{AppInfo.Version}";
    }

    // ------------------------------------------------------------ startup

    public async Task InitializeAppAsync()
    {
        AgentText.Text = $"Agent: {_license.AgentName}";
        if (_license.DaysLeft is int d)
        {
            LicenseStatusText.Text = $"License: {d} days left";
            LicenseStatusText.Foreground = d <= 3 ? B("Error") : d <= 7 ? B("Warning") : B("Success");
        }
        else
        {
            LicenseStatusText.Text = "License: Active";
            LicenseStatusText.Foreground = B("Success");
        }
        VersionText.Text = $"Version: {AppInfo.Version}";
        LicenseKeyText.Text = $"License Key: {AppInfo.MaskLicense(_license.LicenseKey)}";
        HwidText.Text = $"HWID: {_license.Hwid[..Math.Min(20, _license.Hwid.Length)]}...";

        ShowDashboard(this, new RoutedEventArgs());
        await LoadConfigAsync();
    }

    private async Task LoadConfigAsync()
    {
        // Local file first: it's written on every save and can hold local-only
        // settings. Fall back to the server row (fresh machine).
        var cfg = AppConfig.LoadLocal();
        if (cfg == null)
        {
            var row = await _license.LoadRemoteConfigAsync();
            if (row is { } r) cfg = AppConfig.FromServerRow(r);
        }
        _config = cfg ?? new AppConfig();

        UsernameBox.Text = _config.Username;
        PasswordInput.Password = _config.Password;
        LatBox.Text = _config.Latitude;
        LonBox.Text = _config.Longitude;
        CountriesBox.Text = string.Join(", ", _config.AllowedCountries);
        StatesBox.Text = string.Join(", ", _config.AllowedStates);
        IntervalBox.Text = string.IsNullOrWhiteSpace(_config.ServiceInterval) ? "5" : _config.ServiceInterval;
        ShowOnAutoCheck.IsChecked = _config.ShowOnAutoCheck;
        if (_config.GpsMode == "auto") GpsAutoRadio.IsChecked = true; else GpsCustomRadio.IsChecked = true;
        GpsMode_Changed(this, new RoutedEventArgs());
    }

    private void ReadConfigFromUi()
    {
        static List<string> Split(string s) =>
            s.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();

        _config.Username = UsernameBox.Text.Trim();
        _config.Password = PasswordInput.Password.Trim();
        _config.Latitude = LatBox.Text.Trim();
        _config.Longitude = LonBox.Text.Trim();
        _config.AllowedCountries = Split(CountriesBox.Text);
        _config.AllowedStates = Split(StatesBox.Text);
        _config.ServiceInterval = string.IsNullOrWhiteSpace(IntervalBox.Text) ? "5" : IntervalBox.Text.Trim();
        _config.GpsMode = GpsAutoRadio.IsChecked == true ? "auto" : "custom";
        _config.ShowOnAutoCheck = ShowOnAutoCheck.IsChecked == true;
    }

    private async void Save_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            ReadConfigFromUi();
            _config.SaveLocal();
            await _license.SaveRemoteConfigAsync(_config.ToServerRow(_license.Hwid));
            MessageBox.Show("Settings saved!", "Success", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show($"Failed to save: {ex.Message}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void GpsMode_Changed(object sender, RoutedEventArgs e)
    {
        if (LatBox == null) return;
        var custom = GpsCustomRadio.IsChecked == true;
        LatBox.IsEnabled = custom;
        LonBox.IsEnabled = custom;
    }

    // ------------------------------------------------------------ navigation

    private void SetNav(Button active)
    {
        foreach (var b in new[] { DashboardBtn, DetailsBtn, SettingsBtn })
        {
            var on = b == active;
            b.Background = on ? B("Accent") : B("BgCard");
            b.Foreground = on ? Brushes.Black : B("Text");
            b.BorderThickness = new Thickness(on ? 0 : 1);
        }
    }

    private void ShowDashboard(object sender, RoutedEventArgs e)
    {
        DashboardPanel.Visibility = Visibility.Visible;
        DetailsPanel.Visibility = Visibility.Collapsed;
        SettingsPanel.Visibility = Visibility.Collapsed;
        VersionLabel.Visibility = Visibility.Collapsed;
        SetNav(DashboardBtn);
    }

    private void ShowDetails(object sender, RoutedEventArgs e)
    {
        CancelAutoClose();
        DashboardPanel.Visibility = Visibility.Collapsed;
        DetailsPanel.Visibility = Visibility.Visible;
        SettingsPanel.Visibility = Visibility.Collapsed;
        VersionLabel.Visibility = Visibility.Collapsed;
        SetNav(DetailsBtn);
    }

    /// <summary>Used by the UI_PREVIEW build to land on Settings so loaded values can be checked.</summary>
    public void OpenSettings() => ShowSettings(this, new RoutedEventArgs());

    private void ShowSettings(object sender, RoutedEventArgs e)
    {
        CancelAutoClose();
        DashboardPanel.Visibility = Visibility.Collapsed;
        DetailsPanel.Visibility = Visibility.Collapsed;
        SettingsPanel.Visibility = Visibility.Visible;
        VersionLabel.Visibility = Visibility.Visible;
        SetNav(SettingsBtn);
    }

    // ------------------------------------------------------------ auto-check (interval)

    private void AutoSwitch_Click(object sender, RoutedEventArgs e)
    {
        if (AutoSwitch.IsChecked == true) StartAutoCheck(); else StopAutoCheck();
    }

    private void StartAutoCheck()
    {
        _autoInterval = int.TryParse(IntervalBox.Text, out var n) && n > 0 ? n : 5;
        AutoLabel.Text = "ON"; AutoLabel.Foreground = B("Success");
        CountdownLabel.Text = $"Checking every {_autoInterval} min"; CountdownLabel.Foreground = B("Success");

        if (!_isRunning) RunCheck(auto: true);
        _nextCheckTime = DateTime.Now.AddMinutes(_autoInterval);
        _autoTimer.Interval = TimeSpan.FromMinutes(_autoInterval);
        _autoTimer.Start();
        _countdownTimer.Start();
    }

    private void StopAutoCheck()
    {
        _autoTimer.Stop();
        _countdownTimer.Stop();
        AutoLabel.Text = "OFF"; AutoLabel.Foreground = B("TextSecondary");
        CountdownLabel.Text = "";
    }

    private void AutoTimer_Tick(object? sender, EventArgs e)
    {
        if (AutoSwitch.IsChecked != true) { StopAutoCheck(); return; }
        if (!_isRunning) RunCheck(auto: true);
        _nextCheckTime = DateTime.Now.AddMinutes(_autoInterval);
    }

    private void UpdateCountdown()
    {
        if (AutoSwitch.IsChecked != true || _nextCheckTime == null) return;
        var remaining = (_nextCheckTime.Value - DateTime.Now).TotalSeconds;
        if (remaining > 0)
        {
            CountdownLabel.Text = $"Next check in {(int)remaining / 60}:{(int)remaining % 60:00}";
            CountdownLabel.Foreground = B("Accent");
        }
        else
        {
            CountdownLabel.Text = "Checking...";
            CountdownLabel.Foreground = B("Warning");
        }
    }

    // ------------------------------------------------------------ auto-close (stage 2 wires the hide/exit policy)

    private void CancelAutoClose_Click(object sender, RoutedEventArgs e) => CancelAutoClose();

    private void CancelAutoClose() => AutoClosePanel.Visibility = Visibility.Collapsed;

    // ------------------------------------------------------------ check

    private void Run_Click(object sender, RoutedEventArgs e) => RunCheck(auto: false);

    private async void RunCheck(bool auto)
    {
        if (_isRunning) return;
        _currentCheckAuto = auto;
        CancelAutoClose();
        ReadConfigFromUi();

        if (_config.Username.Length == 0) { ShowSettings(this, new RoutedEventArgs()); MessageBox.Show("Username is required", "Settings Required", MessageBoxButton.OK, MessageBoxImage.Warning); return; }
        if (_config.Password.Length == 0) { ShowSettings(this, new RoutedEventArgs()); MessageBox.Show("Password is required", "Settings Required", MessageBoxButton.OK, MessageBoxImage.Warning); return; }

        double? lat = null, lon = null;
        var useAuto = _config.GpsMode == "auto";
        if (!useAuto)
        {
            if (_config.Latitude.Length == 0) { ShowSettings(this, new RoutedEventArgs()); MessageBox.Show("Latitude is required", "Settings Required", MessageBoxButton.OK, MessageBoxImage.Warning); return; }
            if (_config.Longitude.Length == 0) { ShowSettings(this, new RoutedEventArgs()); MessageBox.Show("Longitude is required", "Settings Required", MessageBoxButton.OK, MessageBoxImage.Warning); return; }
            if (!double.TryParse(_config.Latitude, NumberStyles.Float, CultureInfo.InvariantCulture, out var la) ||
                !double.TryParse(_config.Longitude, NumberStyles.Float, CultureInfo.InvariantCulture, out var lo))
            {
                MessageBox.Show("Invalid coordinates!", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                return;
            }
            lat = la; lon = lo;
        }

        _isRunning = true;
        UpdateStatus("running");

        // WebView2 must run on the UI thread; the rest of the pipeline is async I/O
        Func<string, Task<bool>> activate = url => Dispatcher.InvokeAsync(() => LocationActivator.ActivateAsync(url)).Task.Unwrap();
        var runner = new CheckRunner(_license, _data, _config, activate);
        runner.Progress += p => Dispatcher.InvokeAsync(() => Circle.SetProgress(p));
        runner.Status += s => Log.Line($"[check] {s}");

        CheckResult result;
        try { result = await runner.RunAsync(lat, lon, useAuto); }
        catch (Exception ex) { result = new CheckResult(false, ex.Message, new[] { ex.Message }, true); }

        _isRunning = false;
        UpdateStatus(result.Success ? "success" : "error");
        UpdateDetails();
        try { if (result.Success) SystemSounds.Asterisk.Play(); else SystemSounds.Hand.Play(); } catch { }
        Log.Line(result.Success ? "Check OK: Ready to work!" : $"Check FAILED: {string.Join(" | ", result.Errors)}");
    }

    private void UpdateStatus(string status)
    {
        switch (status)
        {
            case "ready":
                Circle.Reset(); StopDots(); RunBtn.IsEnabled = true; RunBtn.Content = "▶  Start";
                break;
            case "running":
                Circle.Start(); RunBtn.IsEnabled = false; _dotPhase = 0; _dotsTimer.Start();
                break;
            case "success":
                StopDots(); Circle.Finish(true); RunBtn.IsEnabled = true; RunBtn.Content = "▶  Start";
                break;
            case "error":
                StopDots(); Circle.Finish(false); RunBtn.IsEnabled = true; RunBtn.Content = "▶  Start";
                break;
        }
    }

    private void StopDots() { _dotsTimer.Stop(); RunBtn.Content = "▶  Start"; }

    private void UpdateDetails()
    {
        (Brush ipColor, string ipStatus) = _data.IpValid switch
        {
            true => (B("Success"), "✓ Valid"),
            false => (B("Error"), "✗ Invalid"),
            _ => (B("Text"), "--"),
        };
        IpText.Text = _data.Ip == "--" ? "---.---.---.---" : _data.Ip; IpText.Foreground = ipColor;
        IpCountry.Text = _data.Country;
        IpLocation.Text = $"{_data.City}, {_data.State}";
        IpIsp.Text = _data.Isp; IpHostname.Text = _data.Hostname; IpType.Text = _data.IpType; IpVersion.Text = _data.IpVersion;
        IpStatus.Text = ipStatus; IpStatus.Foreground = ipColor;

        (Brush gpsColor, string gpsStatus) = _data.CoordValid switch
        {
            true => (B("Success"), "✓ Valid"),
            false => (B("Error"), "✗ Invalid"),
            _ => (B("Text"), "--"),
        };
        GpsCoords.Text = $"{_data.Lat}, {_data.Lon}";
        GpsLocation.Text = $"{_data.CoordCity}, {_data.CoordState}";
        GpsStatus.Text = gpsStatus; GpsStatus.Foreground = gpsColor;
    }
}
