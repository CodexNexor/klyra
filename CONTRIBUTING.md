# Contributing

Thanks for helping improve Klyra.

## Development

```bash
python3 -m py_compile server.py database.py isolation.py controller.py backend.py deploy/run.py
cd frontend
npm install
npm run build
```

## Contribution Rules

- Keep changes scoped and documented.
- Do not commit secrets, databases, logs, tunnel URLs, or local runtime state.
- Do not add offensive automation for unauthorized access.
- Keep examples focused on owned labs, toy targets, CTFs, or defensive validation.
- Update README/docs when behavior changes.

## Pull Request Checklist

- [ ] Build passes.
- [ ] No secrets or generated runtime files are included.
- [ ] New behavior is documented.
- [ ] Security impact is considered.
