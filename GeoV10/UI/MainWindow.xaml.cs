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
    private readonly DispatcherTimer _autoCloseTimer = new() { Interval = TimeSpan.FromSeconds(1) };
    private readonly DispatcherTimer _showFlagTimer = new() { Interval = TimeSpan.FromSeconds(1) };
    private DateTime? _nextCheckTime;
    private int _autoInterval = 5;
    private int _dotPhase;
    private int _autoCloseRemaining;
    private bool _startedHidden;
    private TrayIcon? _tray;

    private Brush B(string key) => (Brush)FindResource(key);

    public MainWindow(LicenseService license)
    {
        InitializeComponent();
        _license = license;
        _autoTimer.Tick += AutoTimer_Tick;
        _countdownTimer.Tick += (_, _) => UpdateCountdown();
        _dotsTimer.Tick += (_, _) => { _dotPhase = (_dotPhase + 1) % 4; RunBtn.Content = new string('●', _dotPhase) + new string('○', 3 - _dotPhase); };
        _autoCloseTimer.Tick += (_, _) => TickAutoClose();
        _showFlagTimer.Tick += (_, _) => { if (SingleInstance.ConsumeShowRequest()) RestoreWindow(); };
        VersionLabel.Text = $"v{AppInfo.Version}";
    }

    /// <summary>Called once after the window is shown/hidden: register startup, watch for
    /// show-requests from a second launch, and run the boot/auto-start check.</summary>
    public void OnStartupComplete(bool startedHidden, bool bootLaunch)
    {
        Log.Line($"OnStartupComplete(startedHidden={startedHidden}, bootLaunch={bootLaunch})");
        _startedHidden = startedHidden;
        _tray = new TrayIcon(onShow: RestoreWindow, onExit: ExitApp);
        try { AutoStart.Ensure(); } catch (Exception e) { Log.Line($"AutoStart.Ensure: {e.Message}"); }
        _showFlagTimer.Start();

        // Only a real boot launch runs the check (robust via BootSession: covers
        // a stale/removed Run key, and never phantom-checks a manual re-open).
        if (bootLaunch)
        {
            ReadConfigFromUi();
            var haveCreds = _config.Username.Length > 0 && _config.Password.Length > 0
                && (_config.GpsMode == "auto" || (_config.Latitude.Length > 0 && _config.Longitude.Length > 0));
            if (haveCreds) { Log.Line("Boot launch - running check"); RunCheck(auto: true); }
            else Log.Line("Auto-check skipped: missing configuration");
        }
    }

    private void ExitApp()
    {
        _tray?.Dispose();
        _tray = null;
        Application.Current.Shutdown();
    }

    protected override void OnClosed(EventArgs e)
    {
        _tray?.Dispose();
        base.OnClosed(e);
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
        TelegramEnabled.IsChecked = _config.TelegramEnabled;
        TelegramChatIds.Text = _config.TelegramChatIds;
        AlertOnSuccess.IsChecked = _config.AlertOnSuccess;
        AlertOnFail.IsChecked = _config.AlertOnFail;
        AlertIp.IsChecked = _config.AlertIp;
        AlertGps.IsChecked = _config.AlertGps;
        if (_config.GpsMode == "auto") GpsAutoRadio.IsChecked = true; else GpsCustomRadio.IsChecked = true;
        GpsMode_Changed(this, new RoutedEventArgs());
        ApplyLocationRules();
    }

    /// <summary>Enforce manager-pushed lists (and lock the fields), or hand control back.</summary>
    private void ApplyLocationRules()
    {
        if (_license.LocationLocked)
        {
            _config.AllowedCountries = new List<string>(_license.EnforcedCountries);
            _config.AllowedStates = new List<string>(_license.EnforcedStates);
            CountriesBox.Text = string.Join(", ", _config.AllowedCountries);
            StatesBox.Text = string.Join(", ", _config.AllowedStates);
        }
        CountriesBox.IsEnabled = StatesBox.IsEnabled = !_license.LocationLocked;
        LocationLockHint.Visibility = _license.LocationLocked ? Visibility.Visible : Visibility.Collapsed;
    }

    private void ReadConfigFromUi()
    {
        static List<string> Split(string s) =>
            s.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList();

        _config.Username = UsernameBox.Text.Trim();
        _config.Password = PasswordInput.Password.Trim();
        _config.Latitude = LatBox.Text.Trim();
        _config.Longitude = LonBox.Text.Trim();
        if (!_license.LocationLocked)
        {
            _config.AllowedCountries = Split(CountriesBox.Text);
            _config.AllowedStates = Split(StatesBox.Text);
        }
        _config.ServiceInterval = string.IsNullOrWhiteSpace(IntervalBox.Text) ? "5" : IntervalBox.Text.Trim();
        _config.GpsMode = GpsAutoRadio.IsChecked == true ? "auto" : "custom";
        _config.ShowOnAutoCheck = ShowOnAutoCheck.IsChecked == true;
        _config.TelegramEnabled = TelegramEnabled.IsChecked == true;
        _config.TelegramChatIds = TelegramChatIds.Text.Trim();
        _config.AlertOnSuccess = AlertOnSuccess.IsChecked == true;
        _config.AlertOnFail = AlertOnFail.IsChecked == true;
        _config.AlertIp = AlertIp.IsChecked == true;
        _config.AlertGps = AlertGps.IsChecked == true;
    }

    private async void ConnectTelegram_Click(object sender, RoutedEventArgs e)
    {
        var dlg = new TelegramConnectWindow(_license.Hwid) { Owner = this };
        dlg.ShowDialog();
        if (dlg.Connected)
        {
            TelegramEnabled.IsChecked = true;
            _tray?.Notify("Telegram", "Account connected", true);
            // Persist so alerts start flowing without a manual Save
            ReadConfigFromUi();
            _config.SaveLocal();
            await _license.SaveRemoteConfigAsync(_config.ToServerRow(_license.Hwid));
        }
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

    // ------------------------------------------------------------ auto-close / background / restore

    private void CancelAutoClose_Click(object sender, RoutedEventArgs e) => CancelAutoClose();

    private void CancelAutoClose()
    {
        _autoCloseTimer.Stop();
        AutoClosePanel.Visibility = Visibility.Collapsed;
    }

    private void StartAutoCloseCountdown()
    {
        if (!IsVisible) return;   // hidden background check: nothing to count down
        CancelAutoClose();
        _autoCloseRemaining = 3;
        AutoClosePanel.Visibility = Visibility.Visible;
        TickAutoClose();
        _autoCloseTimer.Start();
    }

    private void TickAutoClose()
    {
        if (_autoCloseRemaining <= 0) { FinishAutoClose(); return; }
        AutoCloseLabel.Text = $"Closing in {_autoCloseRemaining}s";
        _autoCloseRemaining--;
    }

    private void FinishAutoClose()
    {
        CancelAutoClose();
        // With Auto-Check ON the monitoring loop must survive: hide instead of
        // closing. Re-opening the exe re-shows this instance. With it OFF, close.
        if (AutoSwitch.IsChecked == true)
        {
            Log.Line("Auto-close: hiding window, monitoring continues");
            Hide();
        }
        else
        {
            Close();
        }
    }

    private void RestoreWindow()
    {
        CancelAutoClose();
        try
        {
            Show();
            if (WindowState == WindowState.Minimized) WindowState = WindowState.Normal;
            Activate();
            Topmost = true; Topmost = false;
        }
        catch (Exception e) { Log.Line($"RestoreWindow: {e.Message}"); }
    }

    /// <summary>Hidden auto-check: the window stays hidden unless the check fails.</summary>
    private void ShowIfSilentFailure()
    {
        if (_currentCheckAuto && ShowOnAutoCheck.IsChecked != true && !IsVisible)
        {
            Log.Line("Hidden auto-check failed - showing window");
            RestoreWindow();
        }
    }

    // ------------------------------------------------------------ check

    private void Run_Click(object sender, RoutedEventArgs e) => RunCheck(auto: false);

    private async void RunCheck(bool auto)
    {
        if (_isRunning) return;
        _currentCheckAuto = auto;
        CancelAutoClose();
        // Pick up location rules changed in the manager since startup
        await _license.RefreshLocationRulesAsync();
        ApplyLocationRules();
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

        var location = $"{_data.City}, {_data.State}";
        Stats.Record(result.Success);
        History.Record(result.Success ? "success" : "error", _data.Ip, location,
            result.Success ? "Ready to work!" : string.Join(" | ", result.Errors));
        if (result.Success) _tray?.Notify("Ready to work!", location, true);
        else _tray?.Notify("Location Error", result.Errors.Count > 0 ? result.Errors[0] : result.Message, false);

        _ = SendTelegramAsync(result);

        if (result.Success) StartAutoCloseCountdown();
        else ShowIfSilentFailure();
    }

    /// <summary>Telegram alert with the same error-type detection and filters as the Python app.</summary>
    private async Task SendTelegramAsync(CheckResult result)
    {
        try
        {
            var chatIds = _config.TelegramEnabled ? _config.TelegramChatIds : "";
            var location = $"{_data.City}, {_data.State}";

            if (result.Success)
            {
                await Telegram.SendAlertAsync(_license.LicenseKey, "success", _data.Ip, location,
                    "Ready to work!", chatIds, null,
                    _config.AlertIp, _config.AlertGps, _config.AlertOnFail, _config.AlertOnSuccess);
                return;
            }

            string errorType;
            if (result.SystemError)
            {
                errorType = "system";
            }
            else
            {
                var text = string.Join(" | ", result.Errors).ToLowerInvariant();
                var hasIp = text.Contains("ip:") || text.Contains("ip location") || _data.IpValid == false;
                var hasGps = text.Contains("gps") || text.Contains("coordinate") || _data.CoordValid == false;
                errorType = hasIp && hasGps ? "both" : hasIp ? "ip" : hasGps ? "gps" : "system";
            }

            await Telegram.SendAlertAsync(_license.LicenseKey, "error", _data.Ip, location,
                string.Join(" | ", result.Errors), chatIds, errorType,
                _config.AlertIp, _config.AlertGps, _config.AlertOnFail, _config.AlertOnSuccess);
        }
        catch (Exception e) { Log.Line($"SendTelegram error: {e.Message}"); }
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
