from django.db import migrations


def fix_outstanding_token_user_id(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    user_table = apps.get_model("users", "User")._meta.db_table

    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('token_blacklist_outstandingtoken')")
        if cursor.fetchone()[0] is None:
            return

        cursor.execute(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = 'token_blacklist_outstandingtoken'
              AND column_name = 'user_id'
            """
        )
        row = cursor.fetchone()
        if not row or row[0] == "bigint":
            return

        cursor.execute(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'token_blacklist_outstandingtoken'::regclass
              AND contype = 'f'
            """
        )
        for (constraint_name,) in cursor.fetchall():
            cursor.execute(
                f'ALTER TABLE token_blacklist_outstandingtoken DROP CONSTRAINT "{constraint_name}"'
            )

        cursor.execute("SELECT to_regclass('token_blacklist_blacklistedtoken')")
        if cursor.fetchone()[0] is not None:
            cursor.execute(
                """
                DELETE FROM token_blacklist_blacklistedtoken
                WHERE token_id IN (
                    SELECT id
                    FROM token_blacklist_outstandingtoken
                    WHERE user_id IS NOT NULL
                      AND user_id::text !~ '^[0-9]+$'
                )
                """
            )

        cursor.execute(
            """
            DELETE FROM token_blacklist_outstandingtoken
            WHERE user_id IS NOT NULL
              AND user_id::text !~ '^[0-9]+$'
            """
        )

        cursor.execute(
            """
            ALTER TABLE token_blacklist_outstandingtoken
            ALTER COLUMN user_id TYPE bigint
            USING user_id::text::bigint
            """
        )

        cursor.execute(
            f"""
            ALTER TABLE token_blacklist_outstandingtoken
            ADD CONSTRAINT token_blacklist_outstandingtoken_user_id_83bc629a_fk_users_id
            FOREIGN KEY (user_id)
            REFERENCES {schema_editor.quote_name(user_table)} (id)
            ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED
            """
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("token_blacklist", "0013_alter_blacklistedtoken_options_and_more"),
        ("users", "0002_alter_user_options_alter_user_username"),
    ]

    operations = [
        migrations.RunPython(fix_outstanding_token_user_id, migrations.RunPython.noop),
    ]
