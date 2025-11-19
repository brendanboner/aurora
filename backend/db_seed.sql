-- Create tables if they don't exist
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    topics JSONB DEFAULT '[]'::jsonb,
    organisations JSONB DEFAULT '[]'::jsonb,
    people JSONB DEFAULT '[]'::jsonb,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ------------------------------------------------------------------
-- Insert 4 sample users with profiles tailored to wireless standards
-- ------------------------------------------------------------------

-- USER 1: Wi-Fi standards engineer
INSERT INTO users (name, email)
VALUES ('Alice Standards', 'alice@example.com')
ON CONFLICT DO NOTHING;

INSERT INTO user_preferences (user_id, topics, organisations, people)
SELECT id,
       '["Wi-Fi 6E", "Wi-Fi 7", "802.11be", "AFC Systems"]'::jsonb,
       '["Wi-Fi Alliance", "IEEE 802.11"]'::jsonb,
       '["John Doe", "Jane Smith"]'::jsonb
FROM users WHERE email='alice@example.com'
ON CONFLICT DO NOTHING;

-- USER 2: Security-focused researcher
INSERT INTO users (name, email)
VALUES ('Bob Security', 'bob@example.com')
ON CONFLICT DO NOTHING;

INSERT INTO user_preferences (user_id, topics, organisations, people)
SELECT id,
       '["WPA3", "802.11i", "Zero Trust", "Device Identity"]'::jsonb,
       '["Wi-Fi Alliance", "NIST"]'::jsonb,
       '["Dr. Secure"]'::jsonb
FROM users WHERE email='bob@example.com'
ON CONFLICT DO NOTHING;

-- USER 3: Spectrum and regulatory analyst
INSERT INTO users (name, email)
VALUES ('Carol Spectrum', 'carol@example.com')
ON CONFLICT DO NOTHING;

INSERT INTO user_preferences (user_id, topics, organisations, people)
SELECT id,
       '["6 GHz", "AFC regulation", "FCC updates", "ETSI activities"]'::jsonb,
       '["FCC", "ETSI", "Wi-Fi Alliance"]'::jsonb,
       '["Commissioner Smith"]'::jsonb
FROM users WHERE email='carol@example.com'
ON CONFLICT DO NOTHING;

-- USER 4: Corporate technology strategist
INSERT INTO users (name, email)
VALUES ('Dave Strategist', 'dave@example.com')
ON CONFLICT DO NOTHING;

INSERT INTO user_preferences (user_id, topics, organisations, people)
SELECT id,
       '["AI Networking", "Edge Computing", "Wi-Fi 7", "Enterprise Security"]'::jsonb,
       '["Wi-Fi Alliance", "IEEE", "Cisco"]'::jsonb,
       '["CTO Johnson"]'::jsonb
FROM users WHERE email='dave@example.com'
ON CONFLICT DO NOTHING;
