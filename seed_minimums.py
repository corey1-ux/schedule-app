"""
seed_minimums.py
----------------
Run this once to set bare minimum staffing requirements per skill.
Edit the MINIMUMS dict to match your department needs.
"""
import sqlite3

conn = sqlite3.connect('ir_schedule.db')
conn.row_factory = sqlite3.Row

# Look up skill IDs by name
skills = {r['name']: r['id'] for r in conn.execute('SELECT id, name FROM skills').fetchall()}
print('Skills found:', skills)

# Define your bare minimums — edit these as needed
MINIMUMS = {
    'IR RN': 4,
    'IRC':   1,
    'TL':    1,
    'ECU':   2,
    'Call':  1,
}

inserted = 0
for skill_name, minimum in MINIMUMS.items():
    if skill_name not in skills:
        print(f'WARNING: skill "{skill_name}" not found in database, skipping')
        continue
    skill_id = skills[skill_name]
    conn.execute('''
        INSERT INTO skill_minimums (skill_id, minimum_count)
        VALUES (?, ?)
        ON CONFLICT(skill_id) DO UPDATE SET minimum_count = excluded.minimum_count
    ''', (skill_id, minimum))
    print(f'  Set minimum for {skill_name} (id={skill_id}): {minimum}')
    inserted += 1

conn.commit()
conn.close()
print(f'\nDone. {inserted} minimums set.')