import h5py


# Read file and remove attribute
def remove_attribute(file_path, h5path, attribute_name):
    with h5py.File(file_path, 'r+') as f:
        if h5path in f:
            if attribute_name in f[h5path].attrs:
                del f[h5path].attrs[attribute_name]
                print(
                    f"Attribute '{attribute_name}' removed from {h5path} in {file_path}."
                )
            else:
                print(
                    f"Attribute '{attribute_name}' not found in {h5path} in {file_path}."
                )
                print(f"Available attributes: {list(f[h5path].attrs.keys())}")
        else:
            print(f"Path '{h5path}' not found in {file_path}.")


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Remove an attribute from an HDF5 file.")
    parser.add_argument("file_path", help="Path to the HDF5 file")
    parser.add_argument(
        "h5path",
        help=
        "Path to the HDF5 group or dataset holding the attribute (e.g., '/group/dataset')"
    )
    parser.add_argument("attribute_name",
                        help="Name of the attribute to remove")

    args = parser.parse_args()

    remove_attribute(args.file_path, args.h5path, args.attribute_name)


if __name__ == "__main__":
    main()
