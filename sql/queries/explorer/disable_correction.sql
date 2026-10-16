WITH disabled AS (
    UPDATE app.software_correction
    SET status = 'disabled'
    WHERE id = __CORRECTION_ID__ AND status = 'active'
    RETURNING id
)
SELECT jsonb_build_object('disabled', EXISTS (SELECT 1 FROM disabled));
