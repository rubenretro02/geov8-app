using System.Windows;
using GeoV10.Core;
using GeoV10.UI;

namespace GeoV10;

public partial class App : Application
{
    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        // One instance: a second launch asks the running one to show, then exits.
        if (!SingleInstance.Acquire()) { Shutdown(); return; }
        SingleInstance.ClearStaleFlag();

        Log.Line($"=== Geo {AppInfo.Version} (C#) starting  autostart={AutoStart.LaunchedByAutostart} uptime={AutoStart.UptimeMinutes:F1}m ===");

        try
        {
#if UI_PREVIEW
            {
                var preview = new MainWindow(await Task.Run(() => new LicenseService()));
                MainWindow = preview;
                ShutdownMode = ShutdownMode.OnMainWindowClose;
                var previewHidden = Environment.GetEnvironmentVariable("GEOV10_PREVIEW_HIDDEN") == "1";
                preview.Show();
                if (previewHidden) preview.Hide();
                await preview.InitializeAppAsync();
                if (Environment.GetEnvironmentVariable("GEOV10_PREVIEW_PAGE") == "settings") preview.OpenSettings();
                preview.OnStartupComplete(previewHidden);
                return;
            }
#endif
            // Right after boot the network is often not up yet: wait instead of
            // failing, otherwise the app dies before it can check the license.
            if (!await Net.HasInternetAsync() && !await Net.WaitForInternetAsync())
            {
                MessageBox.Show(
                    "This app requires an internet connection to work.\n\nPlease check your connection and try again.",
                    "No Internet Connection", MessageBoxButton.OK, MessageBoxImage.Error);
                Shutdown();
                return;
            }

            // HWID (WMI, with retries) can take a few seconds right after boot
            var license = await Task.Run(() => new LicenseService());
            var (ok, message) = await license.CheckLicenseAsync();

            if (!ok)
            {
                var dlg = new LicenseWindow(license, message);
                if (dlg.ShowDialog() != true) { Shutdown(); return; }
            }

            var main = new MainWindow(license);
            MainWindow = main;
            ShutdownMode = ShutdownMode.OnMainWindowClose;

            // Auto-checks run hidden by default: when Windows launched us at boot
            // and the user didn't turn on "Show on auto check", start hidden - the
            // window only appears if a check fails or a second launch asks for it.
            var startHidden = AutoStart.LaunchedByAutostart
                              && !(AppConfig.LoadLocal()?.ShowOnAutoCheck ?? false);

            main.Show();
            if (startHidden)
            {
                Log.Line("Auto-check: starting hidden");
                main.Hide();
            }

            await main.InitializeAppAsync();
            main.OnStartupComplete(startHidden);
        }
        catch (Exception ex)
        {
            Log.Line($"Fatal startup error: {ex}");
            MessageBox.Show($"Startup error:\n{ex.Message}", "Geo", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown();
        }
    }
}
