import sqlite3

def check_encoding():
    db_path = 'C:/Users/drkim8864/patchnote-prasia/data/prasia_patchnotes.db'
    conn = sqlite3.connect(db_path)
    try:
        title = conn.execute('SELECT title FROM patch_notes LIMIT 1').fetchone()[0]
        print(f"Original Title: {title}")
        print(f"UTF-8 Hex: {title.encode('utf-8').hex(' ')}")
        
        # '패치노트'라는 단어가 포함되어 있는지 확인
        if '패치노트' in title or '업데이트' in title:
            print("한글이 정상적으로 인식됩니다.")
        else:
            print("한글이 깨진 상태로 보입니다.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_encoding()
