namespace GeoV10.Core;

/// <summary>Mirror of the Python current_data dict shown on the Details page.</summary>
public sealed class CurrentData
{
    public string Ip = "--", Country = "--", State = "--", City = "--", Status = "unknown";
    public string Lat = "--", Lon = "--", CoordCountry = "--", CoordState = "--", CoordCity = "--";
    public string Isp = "--", Hostname = "--", IpType = "--", IpVersion = "--";
    public bool? IpValid, CoordValid;
}

public sealed record CheckResult(bool Success, string Message, IReadOnlyList<string> Errors, bool SystemError);

/// <summary>
/// The check pipeline (_run_check in the Python app): Device Portal → location
/// activation → GPS injection with read-back verification → reverse geocode →
/// public IP → allowed-region checks → server log. UI-agnostic; reports via events.
/// </summary>
public sealed class CheckRunner
{
    private readonly LicenseService _license;
    private readonly CurrentData _data;
    private readonly AppConfig _config;
    private readonly Func<string, Task<bool>> _activateLocation;

    public event Action<int>? Progress;
    public event Action<string>? Status;

    public CheckRunner(LicenseService license, CurrentData data, AppConfig config, Func<string, Task<bool>> activateLocation)
    {
        _license = license;
        _data = data;
        _config = config;
        _activateLocation = activateLocation;
    }

    public async Task<CheckResult> RunAsync(double? lat, double? lon, bool useAutoCoords)
    {
        var errors = new List<string>();
        IpLocation? ipLoc = null;
        GeoLocation? gpsLoc = null;
        string? ip = null;

        async Task<CheckResult> FinishError(string msg)
        {
            _data.Status = "error";
            await _license.LogCheckAsync(ip, ipLoc, gpsLoc, "error", msg);
            return new CheckResult(false, msg, new[] { msg }, SystemError: true);
        }

        try
        {
            Progress?.Invoke(5);

            if (useAutoCoords)
            {
                Status?.Invoke("Getting IP coordinates...");
                Progress?.Invoke(10);
                ip = await GeoServices.GetPublicIpAsync();
                if (ip == null) return await FinishError("Could not get public IP for auto-coords");
                var tmp = await GeoServices.GetLocationDataAsync(ip);
                if (tmp?.Lat == null || tmp.Lon == null) return await FinishError("Could not get coordinates from IP");
                lat = tmp.Lat; lon = tmp.Lon;
                Progress?.Invoke(15);
            }

            if (lat == null || lon == null) return await FinishError("Invalid coordinates!");
            var portal = new DevicePortal(_config.Username.Trim(), _config.Password.Trim());

            Progress?.Invoke(20);
            Status?.Invoke("Connecting to Device Portal...");
            var (portalOk, portalErr) = await portal.TestAsync();
            if (!portalOk)
            {
                if (portalErr == "auth_failed") return await FinishError("Device Portal: Bad username/password");
                Progress?.Invoke(25);
                await Task.Delay(2000);
                (portalOk, portalErr) = await portal.TestAsync();
                if (!portalOk)
                    return await FinishError(portalErr == "auth_failed" ? "Device Portal: Bad username/password" : "Device Portal unavailable");
            }

            Progress?.Invoke(30);
            Status?.Invoke("Activating location...");
            try { await _activateLocation($"{portal.BaseUri}/#Location"); }
            catch (Exception e) { Log.Line($"activate_location_service error: {e.Message}"); }

            Progress?.Invoke(40);
            Status?.Invoke("Setting GPS coordinates...");
            await portal.InitializeLocationAsync();

            Progress?.Invoke(50);
            var injected = false;
            var injectError = "";
            for (var attempt = 0; attempt < 3; attempt++)
            {
                Progress?.Invoke(50 + attempt * 5);
                var (ok, err) = await portal.SetPositionAsync(lat.Value, lon.Value);
                if (ok)
                {
                    await Task.Delay(1000);
                    var readBack = await portal.GetPositionLatitudeAsync();
                    if (readBack.HasValue && readBack.Value != 0)
                    {
                        injected = true;
                        Progress?.Invoke(65);
                        break;
                    }
                }
                injectError = err;
                if (err == "auth_failed") return await FinishError("Device Portal: Bad username/password");
                await Task.Delay(1000);
            }
            if (!injected) return await FinishError($"GPS injection failed: {injectError}");

            _data.Lat = Math.Round(lat.Value, 6).ToString(System.Globalization.CultureInfo.InvariantCulture);
            _data.Lon = Math.Round(lon.Value, 6).ToString(System.Globalization.CultureInfo.InvariantCulture);

            Progress?.Invoke(70);
            Status?.Invoke("Verifying GPS coordinates...");
            gpsLoc = await GeoServices.GetLocationFromCoordinatesAsync(lat.Value, lon.Value);

            Progress?.Invoke(75);
            if (gpsLoc != null)
            {
                _data.CoordCountry = gpsLoc.Country; _data.CoordState = gpsLoc.State; _data.CoordCity = gpsLoc.City;
                var (valid, reason) = AllowedChecker.IsAllowed(gpsLoc.Country, gpsLoc.State, _config.AllowedCountries, _config.AllowedStates);
                _data.CoordValid = valid;
                if (!valid) errors.Add(reason == "country" ? $"GPS: {gpsLoc.Country} not allowed" : $"GPS: {gpsLoc.State} not allowed");
            }
            else
            {
                _data.CoordCountry = _data.CoordState = _data.CoordCity = "Unknown";
                _data.CoordValid = false;
            }

            Progress?.Invoke(80);
            Status?.Invoke("Checking public IP...");
            ip = await GeoServices.GetPublicIpAsync();

            Progress?.Invoke(85);
            if (ip != null)
            {
                _data.Ip = ip;
                ipLoc = await GeoServices.GetLocationDataAsync(ip);
                Progress?.Invoke(90);
                if (ipLoc != null)
                {
                    _data.Country = ipLoc.Country; _data.State = ipLoc.State; _data.City = ipLoc.City;
                    _data.Isp = ipLoc.Isp; _data.Hostname = ipLoc.Hostname; _data.IpType = ipLoc.IpType; _data.IpVersion = ipLoc.IpVersion;
                    var (valid, reason) = AllowedChecker.IsAllowed(ipLoc.Country, ipLoc.State, _config.AllowedCountries, _config.AllowedStates);
                    _data.IpValid = valid;
                    if (!valid) errors.Add(reason == "country" ? $"IP: {ipLoc.Country} not allowed" : $"IP: {ipLoc.State} not allowed");
                }
                else
                {
                    _data.IpValid = false;
                    errors.Add("Could not verify IP location");
                }
            }
            else
            {
                _data.IpValid = false;
                errors.Add("Could not get public IP");
            }

            Progress?.Invoke(95);
            await _license.LogCheckAsync(ip, ipLoc, gpsLoc, errors.Count > 0 ? "error" : "success",
                errors.Count > 0 ? string.Join(" | ", errors) : "OK");

            if (errors.Count > 0)
            {
                _data.Status = "error";
                var first = errors[0];
                return new CheckResult(false, first.Length > 60 ? first[..60] : first, errors, SystemError: false);
            }

            _data.Status = "success";
            return new CheckResult(true, "Ready to work!", errors, SystemError: false);
        }
        catch (Exception e)
        {
            Log.Line($"Check crashed: {e}");
            var msg = e.Message.Length > 50 ? e.Message[..50] : e.Message;
            return await FinishError(msg);
        }
    }
}
