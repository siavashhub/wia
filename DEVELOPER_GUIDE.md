## Dev Workflow
e.g. current release v.0.2.1

### Development Phase
Release branch Creation at the begining of sprint
main → release/0.3

### Release
release/0.3 → merge → main → tag v0.3.0

### Hotfix flow
tag v0.2.1
   ↓
hotfix/0.2.2 branch
   ↓
fix → test
   ↓
merge → main
   ↓
tag v0.2.2
   ↓
merge → release/0.3 (IMPORTANT)



