from gui_v2 import App, load_model, main

if __name__ == '__main__':
    import sys
    if '--validate-packaged' in sys.argv:
        from validate_gui_v2 import main as validate
        try: validate()
        except Exception as exc:
            import json
            from runtime_paths import ROOT
            (ROOT/'validation-failure.json').write_text(json.dumps({'validation':'FAILED','errorType':type(exc).__name__}),encoding='utf-8')
            sys.exit(1)
    elif '--create-shortcut' in sys.argv:
        from desktop_integration import create_shortcut
        create_shortcut()
    else:
        main()
