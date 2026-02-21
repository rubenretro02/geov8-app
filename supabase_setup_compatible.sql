-- =============================================
-- GEO V8.5 - Supabase Tables (COMPATIBLE VERSION)
-- Supports BOTH:
--   1. PowerShell system (license_key based)
--   2. Python system (hardware_id based)
--
-- Run this in your Supabase SQL Editor
-- =============================================

-- =============================================
-- STEP 1: If you already have the licenses table from PowerShell,
-- just add the hardware_id column to it:
-- =============================================

-- Add hardware_id column to existing licenses table (if it doesn't exist)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'licenses' AND column_name = 'hardware_id'
    ) THEN
        ALTER TABLE licenses ADD COLUMN hardware_id TEXT UNIQUE;
    END IF;
END $$;

-- Add agent_name column if it doesn't exist (Python app uses this)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'licenses' AND column_name = 'agent_name'
    ) THEN
        ALTER TABLE licenses ADD COLUMN agent_name TEXT;
    END IF;
END $$;

-- =============================================
-- STEP 2: Create configurations table
-- (Linked by hardware_id for the Python app)
-- =============================================

CREATE TABLE IF NOT EXISTS configurations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    hwid TEXT UNIQUE NOT NULL,
    username TEXT,
    password TEXT,
    port TEXT DEFAULT '50080',
    latitude TEXT,
    longitude TEXT,
    allowed_countries TEXT[] DEFAULT ARRAY['United States', 'USA', 'US'],
    allowed_states TEXT[] DEFAULT ARRAY[]::TEXT[],
    service_interval TEXT DEFAULT '5',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Note: We removed the foreign key constraint to licenses(hardware_id)
-- because hardware_id is added AFTER the license is created
-- The Python app will validate the license separately

-- =============================================
-- STEP 3: Create check_logs table
-- =============================================

CREATE TABLE IF NOT EXISTS check_logs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    hwid TEXT NOT NULL,
    license_key TEXT,
    ip_address TEXT,
    ip_country TEXT,
    ip_state TEXT,
    ip_city TEXT,
    gps_country TEXT,
    gps_state TEXT,
    gps_city TEXT,
    status TEXT NOT NULL,
    message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =============================================
-- STEP 4: Create device_activations table
-- Links license_key to hardware_id
-- =============================================

CREATE TABLE IF NOT EXISTS device_activations (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    license_key TEXT NOT NULL,
    hardware_id TEXT NOT NULL,
    device_name TEXT,
    activated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_seen_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT true,
    UNIQUE(license_key, hardware_id)
);

-- =============================================
-- STEP 5: Enable RLS (Row Level Security)
-- =============================================

ALTER TABLE configurations ENABLE ROW LEVEL SECURITY;
ALTER TABLE check_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_activations ENABLE ROW LEVEL SECURITY;

-- Policies: Allow all operations with anon key
CREATE POLICY "Allow all on configurations" ON configurations
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow all on check_logs" ON check_logs
    FOR ALL USING (true) WITH CHECK (true);

CREATE POLICY "Allow all on device_activations" ON device_activations
    FOR ALL USING (true) WITH CHECK (true);

-- =============================================
-- STEP 6: Create indexes for faster lookups
-- =============================================

CREATE INDEX IF NOT EXISTS idx_configurations_hwid ON configurations(hwid);
CREATE INDEX IF NOT EXISTS idx_check_logs_hwid ON check_logs(hwid);
CREATE INDEX IF NOT EXISTS idx_device_activations_license_key ON device_activations(license_key);
CREATE INDEX IF NOT EXISTS idx_device_activations_hardware_id ON device_activations(hardware_id);
CREATE INDEX IF NOT EXISTS idx_licenses_hardware_id ON licenses(hardware_id);

-- =============================================
-- STEP 7: Function for updated_at trigger
-- =============================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger for configurations
DROP TRIGGER IF EXISTS update_configurations_updated_at ON configurations;
CREATE TRIGGER update_configurations_updated_at
    BEFORE UPDATE ON configurations
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================
-- STEP 8: View to check license by hardware_id
-- This is what the Python app will use
-- =============================================

CREATE OR REPLACE VIEW v_hardware_licenses AS
SELECT
    l.id,
    l.license_key,
    l.hardware_id,
    COALESCE(l.agent_name, l.customer_name, 'Agent') as agent_name,
    l.is_active,
    l.expires_at,
    l.created_at,
    da.activated_at,
    da.last_seen_at
FROM licenses l
LEFT JOIN device_activations da ON l.license_key = da.license_key
WHERE l.is_active = true;

-- =============================================
-- STEP 9: Function to activate a device with a license key
-- Used when first setting up the Python app
-- =============================================

CREATE OR REPLACE FUNCTION activate_device(
    p_license_key TEXT,
    p_hardware_id TEXT,
    p_device_name TEXT DEFAULT NULL
)
RETURNS TABLE(
    success BOOLEAN,
    message TEXT,
    agent_name TEXT
) AS $$
DECLARE
    v_license RECORD;
    v_activation RECORD;
BEGIN
    -- Check if license exists and is valid
    SELECT * INTO v_license
    FROM licenses
    WHERE license_key = p_license_key;

    IF NOT FOUND THEN
        RETURN QUERY SELECT false, 'Invalid license key'::TEXT, NULL::TEXT;
        RETURN;
    END IF;

    IF NOT v_license.is_active THEN
        RETURN QUERY SELECT false, 'License is deactivated'::TEXT, NULL::TEXT;
        RETURN;
    END IF;

    IF v_license.expires_at IS NOT NULL AND v_license.expires_at < NOW() THEN
        RETURN QUERY SELECT false, 'License has expired'::TEXT, NULL::TEXT;
        RETURN;
    END IF;

    -- Check if already activated on this device
    SELECT * INTO v_activation
    FROM device_activations
    WHERE license_key = p_license_key AND hardware_id = p_hardware_id;

    IF FOUND THEN
        -- Update last seen
        UPDATE device_activations
        SET last_seen_at = NOW()
        WHERE license_key = p_license_key AND hardware_id = p_hardware_id;

        RETURN QUERY SELECT true, 'Device already activated'::TEXT,
            COALESCE(v_license.agent_name, v_license.customer_name, 'Agent')::TEXT;
        RETURN;
    END IF;

    -- Create new activation
    INSERT INTO device_activations (license_key, hardware_id, device_name)
    VALUES (p_license_key, p_hardware_id, p_device_name);

    -- Also update the licenses table with hardware_id (for direct lookups)
    UPDATE licenses
    SET hardware_id = p_hardware_id
    WHERE license_key = p_license_key;

    RETURN QUERY SELECT true, 'Device activated successfully'::TEXT,
        COALESCE(v_license.agent_name, v_license.customer_name, 'Agent')::TEXT;
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- STEP 10: Function to check license by hardware_id
-- =============================================

CREATE OR REPLACE FUNCTION check_license_by_hardware(p_hardware_id TEXT)
RETURNS TABLE(
    is_valid BOOLEAN,
    message TEXT,
    agent_name TEXT,
    license_key TEXT,
    expires_at TIMESTAMP WITH TIME ZONE
) AS $$
DECLARE
    v_license RECORD;
    v_activation RECORD;
BEGIN
    -- First check device_activations
    SELECT da.*, l.* INTO v_activation
    FROM device_activations da
    JOIN licenses l ON da.license_key = l.license_key
    WHERE da.hardware_id = p_hardware_id AND da.is_active = true;

    IF FOUND THEN
        -- Check license validity
        IF NOT v_activation.is_active THEN
            RETURN QUERY SELECT false, 'License is deactivated'::TEXT, NULL::TEXT, NULL::TEXT, NULL::TIMESTAMP WITH TIME ZONE;
            RETURN;
        END IF;

        IF v_activation.expires_at IS NOT NULL AND v_activation.expires_at < NOW() THEN
            RETURN QUERY SELECT false, 'License has expired'::TEXT, NULL::TEXT, NULL::TEXT, NULL::TIMESTAMP WITH TIME ZONE;
            RETURN;
        END IF;

        -- Update last seen
        UPDATE device_activations SET last_seen_at = NOW() WHERE hardware_id = p_hardware_id;

        RETURN QUERY SELECT
            true,
            'License valid'::TEXT,
            COALESCE(v_activation.agent_name, v_activation.customer_name, 'Agent')::TEXT,
            v_activation.license_key,
            v_activation.expires_at;
        RETURN;
    END IF;

    -- Also check direct hardware_id in licenses table
    SELECT * INTO v_license
    FROM licenses
    WHERE hardware_id = p_hardware_id;

    IF FOUND THEN
        IF NOT v_license.is_active THEN
            RETURN QUERY SELECT false, 'License is deactivated'::TEXT, NULL::TEXT, NULL::TEXT, NULL::TIMESTAMP WITH TIME ZONE;
            RETURN;
        END IF;

        IF v_license.expires_at IS NOT NULL AND v_license.expires_at < NOW() THEN
            RETURN QUERY SELECT false, 'License has expired'::TEXT, NULL::TEXT, NULL::TEXT, NULL::TIMESTAMP WITH TIME ZONE;
            RETURN;
        END IF;

        RETURN QUERY SELECT
            true,
            'License valid'::TEXT,
            COALESCE(v_license.agent_name, v_license.customer_name, 'Agent')::TEXT,
            v_license.license_key,
            v_license.expires_at;
        RETURN;
    END IF;

    -- No license found
    RETURN QUERY SELECT false, 'No license found for this device'::TEXT, NULL::TEXT, NULL::TEXT, NULL::TIMESTAMP WITH TIME ZONE;
END;
$$ LANGUAGE plpgsql;

-- =============================================
-- DONE!
--
-- How it works:
-- 1. You generate license keys with ADMIN-GenerateKey.ps1 (no changes needed)
-- 2. PowerShell users continue using start.ps1 with license_key
-- 3. Python users need to "activate" their device first:
--    - Enter their license_key in the app
--    - App links hardware_id to that license_key
--    - After activation, app checks by hardware_id
-- =============================================
