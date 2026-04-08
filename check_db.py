import sqlite3

conn = sqlite3.connect('ir_schedule.db')
conn.row_factory = sqlite3.Row

print('=== Tables in DB ===')
rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
for r in rows:
    print(' ', r[0])

print()
print('=== Blocks ===')
try:
    rows = conn.execute('SELECT * FROM schedule_blocks').fetchall()
    for r in rows: print(' ', dict(r))
    if not rows: print('  EMPTY')
except Exception as e:
    print('  Error:', e)

print()
print('=== skill_minimums ===')
try:
    rows = conn.execute('SELECT * FROM skill_minimums').fetchall()
    for r in rows: print(' ', dict(r))
    if not rows: print('  EMPTY - minimums not configured')
except Exception as e:
    print('  Error:', e)

print()
print('=== template_needs ===')
try:
    rows = conn.execute('SELECT * FROM template_needs').fetchall()
    for r in rows: print(' ', dict(r))
    if not rows: print('  EMPTY - no weekly needs set')
except Exception as e:
    print('  Error:', e)

print()
print('=== staff ===')
try:
    rows = conn.execute('SELECT id, name, fte FROM staff').fetchall()
    for r in rows: print(' ', dict(r))
    if not rows: print('  EMPTY')
except Exception as e:
    print('  Error:', e)

print()
print('=== staff_skills ===')
try:
    rows = conn.execute('''
        SELECT st.name as staff, sk.name as skill
        FROM staff_skills ss
        JOIN staff st ON st.id = ss.staff_id
        JOIN skills sk ON sk.id = ss.skill_id
        ORDER BY st.name, sk.name
    ''').fetchall()
    for r in rows: print(' ', dict(r))
    if not rows: print('  EMPTY')
except Exception as e:
    print('  Error:', e)

print()
print('=== requests for all blocks ===')
try:
    rows = conn.execute('''
        SELECT sr.block_id, sr.date, sk.name as skill, st.name as staff
        FROM staff_requests sr
        JOIN skills sk ON sk.id = sr.skill_id
        JOIN staff st ON st.id = sr.staff_id
        ORDER BY sr.block_id, sr.date
        LIMIT 20
    ''').fetchall()
    for r in rows: print(' ', dict(r))
    if not rows: print('  EMPTY')
except Exception as e:
    print('  Error:', e)

conn.close()