"""
seed_minimums.py
----------------
Sets bare minimum staffing per skill per day.
These are hard constraints — the optimizer will never go below these.
Edit MINIMUMS to match your department requirements.
"""
import sqlite3

conn = sqlite3.connect('ir_schedule.db')
conn.row_factory = sqlite3.Row

skills = {r['name']: r['id'] for r in conn.execute('SELECT id, name FROM skills').fetchall()}
print('Skills found:', skills)

# Bare minimums — the absolute floor regardless of day or FTE
MINIMUMS = {
    'TL':    1,
    'IRC':   1,
    'ECU':   2,
    'IR RN': 3,  # Tuesday and Thursday minimum
    'Call':  0,  # managed manually
}

for skill_name, minimum in MINIMUMS.items():
    if skill_name not in skills:
        print(f'WARNING: skill "{skill_name}" not found, skipping')
        continue
    skill_id = skills[skill_name]
    conn.execute('''
        INSERT INTO skill_minimums (skill_id, minimum_count)
        VALUES (?, ?)
        ON CONFLICT(skill_id) DO UPDATE SET minimum_count = excluded.minimum_count
    ''', (skill_id, minimum))
    print(f'  {skill_name}: minimum = {minimum}')

conn.commit()
conn.close()
print('\nDone.')