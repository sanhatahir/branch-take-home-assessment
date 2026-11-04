CREATE SCHEMA IF NOT EXISTS mart;

CREATE OR REPLACE VIEW mart.country_exchange_rates AS
-- Inline this shared query to avoid a stalled materialized self-join in DuckDB 2.0.
WITH country_rates AS NOT MATERIALIZED (
    -- Keep each country-currency mapping with its available USD-based daily rate.
    SELECT
        rates.rate_date,
        countries.country_code,
        countries.country_name,
        currencies.currency_code,
        rates.rate AS usd_rate
    FROM core.countries AS countries
    JOIN core.country_currencies AS currencies
        ON countries.country_code = currencies.country_code
    JOIN core.exchange_rates AS rates
        ON currencies.currency_code = rates.quote_currency
    WHERE rates.base_currency = 'USD'
)
SELECT
    source.rate_date,
    source.country_code AS source_country_code,
    source.country_name AS source_country_name,
    source.currency_code AS source_currency,
    destination.country_code AS destination_country_code,
    destination.country_name AS destination_country_name,
    destination.currency_code AS destination_currency,
    destination.usd_rate / source.usd_rate AS exchange_rate
FROM country_rates AS source
JOIN country_rates AS destination
    ON source.rate_date = destination.rate_date;
