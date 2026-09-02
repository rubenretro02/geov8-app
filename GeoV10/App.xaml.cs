using System.Windows;
using GeoV10.Core;
using GeoV10.UI;

namespace GeoV10;

public partial class App : Application
{
    protected override async void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        Log.Line($"=== Geo {AppInfo.Version} (C#) starting ===");

        try
        {
            // HWID (WMI, with retries) can take a few seconds right after boot
            var license = await Task.Run(() => new LicenseService());
            var (ok, message) = await license.CheckLicenseAsync();

            if (!ok)
            {
                var dlg = new LicenseWindow(license, message);
                if (dlg.ShowDialog() != true)
                {
                    Shutdown();
                    return;
                }
            }

            var main = new MainWindow(license);
            MainWindow = main;
            ShutdownMode = ShutdownMode.OnMainWindowClose;
            main.Show();
            await main.InitializeAppAsync();
        }
        catch (Exception ex)
        {
            Log.Line($"Fatal startup error: {ex}");
            MessageBox.Show($"Startup error:\n{ex.Message}", "Geo", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown();
        }
    }
}
