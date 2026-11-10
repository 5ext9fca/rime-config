"""备份后应用 config/fcitx5/theme.json 外观，不修改输入行为。"""
import sys
from pathlib import Path
if not __package__:
    sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
import argparse
from pathlib import Path
from client.platforms.linux.theme import apply


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    from client.project import ROOT
    root=ROOT
    state=root/'private/fcitx5-theme'
    print(apply(root/'config',state,args.dry_run))
    from client.config.automation import load
    from client.maintenance.backup_retention import clean
    report=clean(state,load(root/'automation.json')['backups'],args.dry_run)
    print('Theme backup retention:',report['status'],'deleted:',report['deleted'])


if __name__=='__main__':main()
