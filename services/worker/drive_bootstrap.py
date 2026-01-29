from services.worker.drive import get_drive_service, ensure_drive_schema

if __name__ == "__main__":
    service = get_drive_service()
    schema = ensure_drive_schema(service)
    print("Drive schema ensured:")
    for key, value in schema.items():
        print(f"{key}: {value}")
