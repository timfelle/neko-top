import h5py


# Read file and remove attribute
def remove_attribute(file_path, h5path, attribute_name):
    with h5py.File(file_path, 'r+') as f:
        if h5path in f:
            if attribute_name in f[h5path].attrs:
                del f[h5path].attrs[attribute_name]
            else:
                print(
                    f"Attribute '{attribute_name}' not found in {h5path} in {file_path}."
                )
                print(f"Available attributes: {list(f[h5path].attrs.keys())}")
        else:
            print(f"Path '{h5path}' not found in {file_path}.")


# Find all attributes recursively with the given name in the HDF5 file
def find_attributes(file_path, attribute_name) -> list[str]:
    found = []
    with h5py.File(file_path, 'r') as f:

        def search_attrs(group):
            for key in group.keys():
                item = group[key]
                if attribute_name in item.attrs:
                    found.append(item.name)
                if isinstance(item, h5py.Group):
                    search_attrs(item)

        search_attrs(f)

    return found


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Remove an attribute from an HDF5 file.")
    parser.add_argument("file_path", help="Path to the HDF5 file")
    parser.add_argument("attribute_name",
                        help="Name of the attribute to remove")
    parser.add_argument(
        "--h5path",
        help=
        "Path to the HDF5 group or dataset holding the attribute (e.g., '/group/dataset')"
    )

    args = parser.parse_args()

    if args.h5path:
        h5paths = [args.h5path]
    else:
        h5paths = find_attributes(args.file_path, args.attribute_name)

    if not h5paths:
        print(
            f"No attributes named '{args.attribute_name}' found in {args.file_path}."
        )
        return
    elif len(h5paths) > 1:
        print(
            f"Found {len(h5paths)} occurrences of attribute '{args.attribute_name}':"
        )

    print(f"Removing attribute: {args.attribute_name} from {args.file_path}:")
    for h5path in h5paths:
        print(f"- Removed from {h5path}.")
        remove_attribute(args.file_path, h5path, args.attribute_name)


if __name__ == "__main__":
    main()
