#!/usr/bin/env python3

import os
import re
import json
import shutil
from pathlib import Path
from base64 import b64decode
from typing import Dict, List, Union

import yaml
import pypandoc

CWD = os.path.dirname(os.path.realpath(__file__))


def update_sphinx_tags(rst: str) -> str:
    """
    Update `.. container :: {tag}` to `.. {tag}::`

    :param rst: The converted rst source
    :return:
    """
    return re.sub(r"\.\. container:: (\w+)", r".. \1::", rst)


def add_property_newline(rst: str) -> str:
    """
    If a line ends as following:

    foobar :property=lorem

    Then it is updated to:

    foobar
    :property=lorem
    """
    return re.sub(r"(\w+) (:property=)", r"\1\n   \2", rst)


def generate_code_output_block(output_source: List[str] = None, only_header: bool = False) -> str:
    output_header = "\n".join(
        [
            f"# {line}"
            for line in [
                ".. rst-class :: sphx-glr-script-out",
                "",
                "Out:",
                "",
                ".. code-block: none",
                "",
            ]
        ]
    )
    if only_header:
        return output_header
    output_text = (
        "\n" + "\n".join([f"#    {line.rstrip()}" for line in output_source])
        if output_source
        else ""
    )
    return f"\n\n{'#' * 70}\n{output_header}{output_text}"


def generate_sphinx_role_comment(role_name: str, target: str, **attrs: Union[str, int]) -> str:
    return "\n".join(
        [
            f"# .. {role_name}:: {target}",
            *[f"#    :{attr_name}: {attr_value}" for attr_name, attr_value in attrs.items()],
        ]
    )


def set_author_info(author_info: Dict, authors_dir: Union[str, Path]) -> str:
    name = author_info["name"]
    profile_picture_loc = Path(author_info["profile_picture"])
    profile_picture_loc = (
        profile_picture_loc if profile_picture_loc.is_absolute() else CWD / profile_picture_loc
    )
    bio = author_info.get("bio", "")

    name_formatted = author_info.get(
        "formatted_name", re.sub(r"[ \-'\u0080-\uFFFF]+", "_", name).lower()
    )
    profile_picture_suffix = "".join(profile_picture_loc.suffixes)
    new_profile_picture_name = f"{name_formatted}{profile_picture_suffix}"
    new_profile_picture_loc = Path(authors_dir) / new_profile_picture_name
    new_profile_picture_save_loc = (
        new_profile_picture_loc
        if new_profile_picture_loc.is_absolute()
        else CWD / new_profile_picture_loc
    )
    info_file_name = f"{name_formatted}.txt"
    info_file_loc = Path(authors_dir) / info_file_name
    info_file_save_loc = info_file_loc if info_file_loc.is_absolute() else CWD / info_file_loc

    shutil.copy(profile_picture_loc, new_profile_picture_save_loc)

    author_txt = f""".. bio:: {name}
   :photo: {new_profile_picture_loc}

   {bio}
    """
    with info_file_save_loc.open("w") as fh:
        fh.write(author_txt)

    author_sphinx = ["About the author", "----------------", f".. include:: {info_file_loc}"]
    author_sphinx_txt = "\n".join([f"# {line}" for line in author_sphinx])
    return f"\n\n{'#' * 70}\n{author_sphinx_txt}"


def fix_image_alt_tag_as_text(rst: str) -> str:
    return re.sub(r" {3}:alt: (.+)\n\n {3}(.+)", r"   :alt: \1", rst)


def convert_notebook_to_python(
    notebook: Dict,
    notebook_name: str,
    is_executable: bool,
    sphinx_gallery_dir_name: str,
    notebook_asset_folder_name: str,
) -> str:
    # Initial validations
    assert "cells" in notebook
    assert isinstance(notebook["cells"], list)
    assert len(notebook["cells"])
    assert notebook["cells"][0]["cell_type"] == "markdown"

    ret_python_str = ""

    for i, cell in enumerate(notebook["cells"]):
        cell_type = cell["cell_type"]
        cell_source = "".join(cell.get("source", []))

        if cell_type == "markdown" and cell_source:
            cell_rst_source = pypandoc.convert_text(
                cell_source, format="md", to="rst", extra_args=["--wrap=auto", "--columns=100"]
            )
            cell_rst_source_formatted = fix_image_alt_tag_as_text(
                add_property_newline(update_sphinx_tags(cell_rst_source))
            )

            # First cell (Header)
            if i == 0:
                ret_python_str = f'r"""{cell_rst_source_formatted}"""'
            else:  # Subsequent text sections
                commented_source = "\n".join(
                    [f"# {line}" for line in cell_rst_source_formatted.split("\n")]
                )

                ret_python_str += f"\n\n{'#' * 70}\n{commented_source}"
        elif cell_type == "code" and cell_source:
            ret_python_str += f"\n\n{cell_source}"
            if not is_executable:
                # The output needs to be put into the demo file
                code_outputs = cell.get("outputs", [])
                num_images = 0
                for j, output in enumerate(code_outputs):
                    output_data = output.get("data")
                    if output["output_type"] == "execute_result" and "text/plain" in output_data:
                        ret_python_str += generate_code_output_block(
                            output_data["text/plain"], only_header=j != 0
                        )
                    elif output["output_type"] == "display_data":
                        cell_id = cell["id"]
                        if "text/plain" in output_data and "image/png" not in output_data:
                            if j == 0:
                                ret_python_str += generate_code_output_block()
                            ret_python_str += "\n" + "\n".join(
                                [f"#    {line.strip()}" for line in output_data["text/plain"]]
                            )

                        if "image/png" in output_data:
                            if j == 0:
                                ret_python_str += f"\n\n{'#' * 70}"
                            num_images += 1
                            image_file_dir = (
                                Path(sphinx_gallery_dir_name) / notebook_asset_folder_name
                            )
                            image_file_path = (
                                image_file_dir / f"{notebook_name}_{cell_id}_{num_images}.png"
                            )
                            role_text = generate_sphinx_role_comment(
                                "figure", image_file_path.as_posix(), align="center", width="80%"
                            )
                            image_data = b64decode(output_data["image/png"])
                            image_save_loc = (
                                image_file_path
                                if image_file_path.is_absolute()
                                else (CWD / image_file_path)
                            )
                            if not image_save_loc.exists():
                                image_save_loc.mkdir(parents=True)
                            with open(image_save_loc, "wb") as ifh:
                                ifh.write(image_data)
                            ret_python_str += f"\n#\n{role_text}"
                    elif output["output_type"] == "stream":
                        text = output.get("text")
                        if text:
                            ret_python_str += generate_code_output_block(text)
    else:
        ret_python_str = ret_python_str.replace("\n%", "\n# %")

    return ret_python_str


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert Jupyter Notebook to QML Demo")

    parser.add_argument("file", help="Path to file that needs to be converted")

    parser.add_argument(
        "--is-executable",
        help="Indicate if the notebook is executable. "
        "If not passed, this information is inferred "
        "from the notebook file name. "
        "If the notebook name startswith tutotial_, "
        "then it is treated as executable.",
        action="store_true",
    )
    parser.add_argument(
        "--sphinx-gallery-dir",
        help="The path to the directory for Sphinx Gallery. "
        "(AKA: The directory that holds all the demos)",
        default="../demonstrations",
    )
    parser.add_argument(
        "--authors-directory",
        help="Directory where all author asset information " "will be saved",
        default="../_static/authors",
    )

    parser.add_argument(
        "--author-file", help="The path to the YAML file containing Author information"
    )

    results = parser.parse_args()

    notebook_file = Path(results.file)
    notebook_file_name = notebook_file.stem
    notebook_is_executable = notebook_file_name.startswith("tutorial_") or results.is_executable
    notebook_assets_folder_name = (
        notebook_file_name[len("tutorial_") :]
        if notebook_file_name.startswith("tutorial_")
        else notebook_file_name
    )
    sphinx_gallery_dir = Path(results.sphinx_gallery_dir)

    with notebook_file.open() as fh:
        nb = json.load(fh)

    with open(results.author_file) as fh:
        author = yaml.safe_load(fh)

    author_sphinx = set_author_info(author, results.authors_directory)

    nb_py = convert_notebook_to_python(
        nb,
        notebook_file_name,
        notebook_is_executable,
        results.sphinx_gallery_dir,
        notebook_assets_folder_name,
    )

    nb_py += author_sphinx

    gallery_save_loc = (
        sphinx_gallery_dir if sphinx_gallery_dir.is_absolute() else CWD / sphinx_gallery_dir
    )
    with (gallery_save_loc / f"{notebook_file_name}.py").open("w") as fh:
        fh.write(nb_py)
