namespace GeoV10.Core;

/// <summary>Constants shared by the whole app. Same backend as the Python app.</summary>
public static class AppInfo
{
    public const string Version = "10.0.2.0";

    public const string SupabaseUrl = "https://krejyqdlujpemrpeqozc.supabase.co";
    public const string SupabaseKey = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImtyZWp5cWRsdWpwZW1ycGVxb3pjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzAzMjA2ODgsImV4cCI6MjA4NTg5NjY4OH0.uEtY3u8Y2dbM5o_B0xHku7RU91u0iAuY7EJBCyOAxQY";
    public const string LicenseManagerUrl = "https://geov8-license-manager.vercel.app";

    public const int DevicePortalPort = 50080;

    public static readonly string[] DefaultAllowedCountries = { "United States", "USA", "US" };
    public static readonly string[] DefaultAllowedStates = { "Florida", "Texas" };

    /// <summary>First 4 + last 4 only, e.g. 6ZWN•••••••••••NUNV, so a key can't be read off the screen.</summary>
    public static string MaskLicense(string? key)
    {
        if (string.IsNullOrWhiteSpace(key)) return "";
        var k = key.Trim();
        if (k.Length <= 8) return k;
        return k[..4] + new string('•', k.Length - 8) + k[^4..];
    }
}
