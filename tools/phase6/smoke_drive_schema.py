from services.worker.drive import get_drive_service, load_drive_schema

if __name__ == "__main__":
    service = get_drive_service()
    schema = load_drive_schema(service)
    print("Drive schema OK:")
    for key in sorted(schema.keys()):
        print(f"{key}: {schema[key]}")
