"""Profile supplied archive without extracting personal information."""
import collections
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

def profile(path):
    result={}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            if not name.endswith('.csv'):continue
            rows=list(csv.DictReader(io.StringIO(z.read(name).decode('utf-8-sig'))))
            if not rows:continue
            key=next(iter(rows[0]));ids=[r[key].strip() for r in rows]
            if name=='data_dictionary.csv':
                key='dataset,column';ids=[r['dataset'].strip()+','+r['column'].strip() for r in rows]
            result[name]=dict(rows=len(rows),primary_key=key,duplicate_ids=len(ids)-len(set(ids)),blank_ids=sum(not i for i in ids))
            if name=='calls.csv':
                unique={r['call_id'].strip():r for r in rows}
                result[name]['status_counts']=dict(collections.Counter(r['call_status'] for r in unique.values()))
                result[name]['warning']='Last physical row retained for profiling only; conflicting records require timestamp-aware reconciliation before training.'
    return result
if __name__=='__main__':
    result=profile(sys.argv[1]);Path('dataset_profile.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))

