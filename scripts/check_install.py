"""Read installed package metadata in the selected interpreter; no installs/GPU/network."""
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import sys

def inventory(engine):
    root=Path(__file__).resolve().parents[1]
    pins={}
    if engine=='diffusers':
        for line in (root/'constraints/h100-cu126-diffusers.txt').read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '==' in line:
                name,version=line.strip().split('==',1);pins[name]=version
    names=list(pins) if pins else ['sglang','torch','torchvision','torchaudio']
    rows=[]
    for name in names:
        try:
            dist=metadata.distribution(name);version=dist.version
            row={'name':name,'installed':version,'location':str(dist.locate_file(''))}
            if name in pins:
                row.update(expected=pins[name],matches_pin=version.split('+',1)[0]==pins[name])
            requirement=dist.metadata.get('Requires-Python')
            if requirement:row['requires_python']=requirement
        except metadata.PackageNotFoundError:
            row={'name':name,'installed':None,**({'expected':pins[name],'matches_pin':False} if name in pins else {})}
        rows.append(row)
    return {'python':sys.executable,'python_version':sys.version.split()[0],'engine':engine,'packages':rows}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=['diffusers','sglang'],required=True)
    args=parser.parse_args()
    print(json.dumps(inventory(args.engine),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
