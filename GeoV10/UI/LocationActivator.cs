using System.Windows;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
using GeoV10.Core;

namespace GeoV10.UI;

/// <summary>
/// Replaces the headless Selenium browser of the Python app with WebView2 (built
/// into Windows 10/11 - no chromedriver/msedgedriver, no webdriver_manager, which
/// is what broke GPS injection on VMs). Loads the Device Portal #Location page in
/// an off-screen window and clicks through the certificate prompt if it appears.
/// Best effort: any failure just returns false, exactly like the Python version.
/// Must be called on the UI thread.
/// </summary>
public static class LocationActivator
{
    public static async Task<bool> ActivateAsync(string url)
    {
        Window? host = null;
        try
        {
            var env = await CoreWebView2Environment.CreateAsync(userDataFolder: Paths.WebView2Data);
            var web = new WebView2();
            host = new Window
            {
                Width = 800, Height = 600,
                Left = -10000, Top = -10000,          // off-screen
                WindowStyle = WindowStyle.None,
                ShowInTaskbar = false, ShowActivated = false,
                Opacity = 0, Content = web,
            };
            host.Show();
            await web.EnsureCoreWebView2Async(env);
            web.CoreWebView2.Settings.AreDefaultScriptDialogsEnabled = false;

            await NavigateAsync(web, url, TimeSpan.FromSeconds(8));
            await Task.Delay(2000);

            if ((web.Source?.ToString() ?? "").Contains("certprompt", StringComparison.OrdinalIgnoreCase))
            {
                try
                {
                    await web.CoreWebView2.ExecuteScriptAsync(
                        "document.querySelectorAll('input[type=\"checkbox\"]').forEach(c=>{if(!c.checked)c.click()});");
                    await Task.Delay(500);
                    await web.CoreWebView2.ExecuteScriptAsync(
                        "document.querySelectorAll('button').forEach(b=>{if(b.textContent.toLowerCase().includes('continue'))b.click()});");
                    await Task.Delay(2000);
                }
                catch { }
            }

            await NavigateAsync(web, url, TimeSpan.FromSeconds(8));
            await Task.Delay(2000);
            return true;
        }
        catch (Exception e)
        {
            Log.Line($"LocationActivator (WebView2) failed: {e.Message}");
            return false;
        }
        finally
        {
            try { host?.Close(); } catch { }
        }
    }

    private static async Task NavigateAsync(WebView2 web, string url, TimeSpan timeout)
    {
        var tcs = new TaskCompletionSource<bool>();
        void Done(object? s, CoreWebView2NavigationCompletedEventArgs e) => tcs.TrySetResult(e.IsSuccess);
        web.CoreWebView2.NavigationCompleted += Done;
        try
        {
            web.CoreWebView2.Navigate(url);
            await Task.WhenAny(tcs.Task, Task.Delay(timeout));
        }
        finally { web.CoreWebView2.NavigationCompleted -= Done; }
    }
}
