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
#if UI_PREVIEW
            // Local UI preview ONLY - compiled with `dotnet build -p:DefineConstants=UI_PREVIEW`,
            // never part of a release build. Opens the main window without a license check
            // so the XAML can be eyeballed on a dev machine.
            {
                var preview = new MainWindow(await Task.Run(() => new LicenseService()));
                MainWindow = preview;
                ShutdownMode = ShutdownMode.OnMainWindowClose;
                preview.Show();
                await preview.InitializeAppAsync();
                if (Environment.GetEnvironmentVariable("GEOV10_PREVIEW_PAGE") == "settings") preview.OpenSettings();
                return;
            }
#endif
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
