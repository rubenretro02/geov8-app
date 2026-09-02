using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace GeoV10.Core;

/// <summary>
/// Settings, stored in config_local.json with the exact keys the Python app used
/// so existing files load unchanged. Unknown keys are preserved round-trip.
/// </summary>
public sealed class AppConfig
{
    [JsonPropertyName("username")] public string Username { get; set; } = "";
    [JsonPropertyName("password")] public string Password { get; set; } = "";
    [JsonPropertyName("latitude"), JsonConverter(typeof(LenientStringConverter))] public string Latitude { get; set; } = "";
    [JsonPropertyName("longitude"), JsonConverter(typeof(LenientStringConverter))] public string Longitude { get; set; } = "";
    [JsonPropertyName("allowed_countries")] public List<string> AllowedCountries { get; set; } = new(AppInfo.DefaultAllowedCountries);
    [JsonPropertyName("allowed_states")] public List<string> AllowedStates { get; set; } = new(AppInfo.DefaultAllowedStates);
    [JsonPropertyName("service_interval"), JsonConverter(typeof(LenientStringConverter))] public string ServiceInterval { get; set; } = "5";
    [JsonPropertyName("telegram_enabled")] public bool TelegramEnabled { get; set; }
    [JsonPropertyName("telegram_chat_ids"), JsonConverter(typeof(LenientStringConverter))] public string TelegramChatIds { get; set; } = "";
    [JsonPropertyName("gps_mode")] public string GpsMode { get; set; } = "custom";
    [JsonPropertyName("alert_ip")] public bool AlertIp { get; set; } = true;
    [JsonPropertyName("alert_gps")] public bool AlertGps { get; set; } = true;
    [JsonPropertyName("alert_on_fail")] public bool AlertOnFail { get; set; } = true;
    [JsonPropertyName("alert_on_success")] public bool AlertOnSuccess { get; set; }
    /// <summary>Local-only: auto-checks run hidden unless this is on.</summary>
    [JsonPropertyName("show_on_auto_check")] public bool ShowOnAutoCheck { get; set; }

    [JsonExtensionData] public Dictionary<string, JsonElement>? Extra { get; set; }

    private static readonly JsonSerializerOptions Options = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
    };

    public static AppConfig? LoadLocal()
    {
        try
        {
            if (!File.Exists(Paths.Config)) return null;
            return JsonSerializer.Deserialize<AppConfig>(File.ReadAllText(Paths.Config), Options);
        }
        catch (Exception e)
        {
            Log.Line($"Config load error: {e.Message}");
            return null;
        }
    }

    public static AppConfig? FromServerRow(JsonElement row)
    {
        try { return JsonSerializer.Deserialize<AppConfig>(row.GetRawText(), Options); }
        catch (Exception e)
        {
            Log.Line($"Server config parse error: {e.Message}");
            return null;
        }
    }

    public void SaveLocal()
    {
        File.WriteAllText(Paths.Config, JsonSerializer.Serialize(this, Options));
    }

    /// <summary>
    /// Only the columns that exist in the configurations table. PostgREST rejects
    /// the whole row on an unknown key, which is how the Python app once lost
    /// every settings change silently.
    /// </summary>
    public Dictionary<string, object?> ToServerRow(string hwid) => new()
    {
        ["hardware_id"] = hwid,
        ["username"] = Username,
        ["password"] = Password,
        ["latitude"] = Latitude,
        ["longitude"] = Longitude,
        ["allowed_countries"] = AllowedCountries,
        ["allowed_states"] = AllowedStates,
        ["service_interval"] = ServiceInterval,
        ["telegram_enabled"] = TelegramEnabled,
        ["telegram_chat_ids"] = TelegramChatIds,
        ["gps_mode"] = GpsMode,
        ["alert_ip"] = AlertIp,
        ["alert_gps"] = AlertGps,
        ["alert_on_fail"] = AlertOnFail,
        ["alert_on_success"] = AlertOnSuccess,
    };
}

/// <summary>Reads a string property that may have been stored as a number/bool by an older version.</summary>
public sealed class LenientStringConverter : JsonConverter<string>
{
    public override string Read(ref Utf8JsonReader reader, Type typeToConvert, JsonSerializerOptions options) =>
        reader.TokenType switch
        {
            JsonTokenType.String => reader.GetString() ?? "",
            JsonTokenType.Number => reader.TryGetInt64(out var l) ? l.ToString() : reader.GetDouble().ToString(System.Globalization.CultureInfo.InvariantCulture),
            JsonTokenType.True => "true",
            JsonTokenType.False => "false",
            JsonTokenType.Null => "",
            _ => throw new JsonException($"Unexpected token {reader.TokenType} for string"),
        };

    public override void Write(Utf8JsonWriter writer, string value, JsonSerializerOptions options) =>
        writer.WriteStringValue(value);
}
