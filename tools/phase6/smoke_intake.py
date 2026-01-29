from services.worker.drive import get_drive_service, load_drive_schema, list_files

if __name__ == "__main__":
    service = get_drive_service()
    schema = load_drive_schema(service)
    manifests = list_files(service, schema["INBOX_MANIFESTS"])
    print(f"Manifests found: {len(manifests)}")
    for m in manifests[:5]:
        print(f"- {m['name']} ({m['id']})")
