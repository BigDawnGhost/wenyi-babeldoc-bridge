// Generated from BabelDOC 0.7.1's field declarations; do not edit by hand.
impl Loader {
    fn data(&mut self, kind: &str, value: &Value, path: &str) -> Result<NodeData> {
        Ok(match kind {
            "BaseOperations" => NodeData::BaseOperations(DataBaseOperations {
                value: scalar::<String>(&value["value"])?,
            }),
            "Box" => NodeData::Box(DataBox {
                x: scalar::<Option<f64>>(&value["x"])?,
                y: scalar::<Option<f64>>(&value["y"])?,
                x2: scalar::<Option<f64>>(&value["x2"])?,
                y2: scalar::<Option<f64>>(&value["y2"])?,
            }),
            "GraphicState" => NodeData::GraphicState(DataGraphicState {
                passthrough_per_char_instruction: self
                    .instructions(&value["passthrough_per_char_instruction"])?,
            }),
            "PdfAffineTransform" => NodeData::PdfAffineTransform(DataPdfAffineTransform {
                translation_x: scalar::<Option<f64>>(&value["translation_x"])?,
                translation_y: scalar::<Option<f64>>(&value["translation_y"])?,
                rotation: scalar::<Option<f64>>(&value["rotation"])?,
                scale_x: scalar::<Option<f64>>(&value["scale_x"])?,
                scale_y: scalar::<Option<f64>>(&value["scale_y"])?,
                shear: scalar::<Option<f64>>(&value["shear"])?,
            }),
            "PdfFontCharBoundingBox" => {
                NodeData::PdfFontCharBoundingBox(DataPdfFontCharBoundingBox {
                    x: scalar::<Option<f64>>(&value["x"])?,
                    y: scalar::<Option<f64>>(&value["y"])?,
                    x2: scalar::<Option<f64>>(&value["x2"])?,
                    y2: scalar::<Option<f64>>(&value["y2"])?,
                    char_id: scalar::<Option<i64>>(&value["char_id"])?,
                })
            }
            "PdfInlineForm" => NodeData::PdfInlineForm(DataPdfInlineForm {
                form_data: scalar::<Option<String>>(&value["form_data"])?,
                image_parameters: scalar::<Option<String>>(&value["image_parameters"])?,
            }),
            "PdfMatrix" => NodeData::PdfMatrix(DataPdfMatrix {
                a: scalar::<Option<f64>>(&value["a"])?,
                b: scalar::<Option<f64>>(&value["b"])?,
                c: scalar::<Option<f64>>(&value["c"])?,
                d: scalar::<Option<f64>>(&value["d"])?,
                e: scalar::<Option<f64>>(&value["e"])?,
                f: scalar::<Option<f64>>(&value["f"])?,
            }),
            "PdfPath" => NodeData::PdfPath(DataPdfPath::new(
                scalar(&value["x"])?,
                scalar(&value["y"])?,
                scalar::<Option<String>>(&value["op"])?.map(PathOp::from),
                scalar(&value["has_xy"])?,
            )),
            "PdfXobjForm" => NodeData::PdfXobjForm(DataPdfXobjForm {
                xref_id: scalar::<Option<i64>>(&value["xref_id"])?,
                do_args: scalar::<Option<String>>(&value["do_args"])?,
            }),
            "Cropbox" => NodeData::Cropbox(DataCropbox {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
            }),
            "Mediabox" => NodeData::Mediabox(DataMediabox {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
            }),
            "PageLayout" => NodeData::PageLayout(DataPageLayout {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
                id: scalar::<Option<i64>>(&value["id"])?,
                conf: scalar::<Option<f64>>(&value["conf"])?,
                class_name: scalar::<Option<String>>(&value["class_name"])?,
            }),
            "PdfFigure" => NodeData::PdfFigure(DataPdfFigure {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
            }),
            "PdfFont" => NodeData::PdfFont(DataPdfFont {
                pdf_font_char_bounding_box: self.many(
                    "PdfFontCharBoundingBox",
                    &value["pdf_font_char_bounding_box"],
                    &format!("{path}.pdf_font_char_bounding_box"),
                )?,
                name: scalar::<Option<String>>(&value["name"])?,
                font_id: scalar::<Option<String>>(&value["font_id"])?,
                xref_id: scalar::<Option<i64>>(&value["xref_id"])?,
                encoding_length: scalar::<Option<i64>>(&value["encoding_length"])?,
                font_subtype: scalar::<Option<String>>(&value["font_subtype"])?,
                type3_font_matrix: scalar::<Option<String>>(&value["type3_font_matrix"])?,
                type3_font_bbox: scalar::<Option<String>>(&value["type3_font_bbox"])?,
                type3_em_height: scalar::<Option<f64>>(&value["type3_em_height"])?,
                bold: scalar::<Option<babeldoc_il_types::RuntimeBool>>(&value["bold"])?,
                italic: scalar::<Option<babeldoc_il_types::RuntimeBool>>(&value["italic"])?,
                monospace: scalar::<Option<babeldoc_il_types::RuntimeBool>>(&value["monospace"])?,
                serif: scalar::<Option<babeldoc_il_types::RuntimeBool>>(&value["serif"])?,
                ascent: scalar::<Option<f64>>(&value["ascent"])?,
                descent: scalar::<Option<f64>>(&value["descent"])?,
            }),
            "PdfFormSubtype" => NodeData::PdfFormSubtype(DataPdfFormSubtype {
                pdf_inline_form: self.optional(
                    "PdfInlineForm",
                    &value["pdf_inline_form"],
                    &format!("{path}.pdf_inline_form"),
                )?,
                pdf_xobj_form: self.optional(
                    "PdfXobjForm",
                    &value["pdf_xobj_form"],
                    &format!("{path}.pdf_xobj_form"),
                )?,
            }),
            "PdfOriginalPath" => NodeData::PdfOriginalPath(DataPdfOriginalPath {
                pdf_path: self.optional(
                    "PdfPath",
                    &value["pdf_path"],
                    &format!("{path}.pdf_path"),
                )?,
            }),
            "PdfOriginalPathPrimitive" => {
                NodeData::PdfOriginalPathPrimitive(DataPdfOriginalPathPrimitive {
                    op: scalar::<Option<String>>(&value["op"])?,
                    args: scalar::<Vec<f64>>(&value["args"])?,
                })
            }
            "PdfRectangle" => NodeData::PdfRectangle(DataPdfRectangle {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
                graphic_state: self.optional(
                    "GraphicState",
                    &value["graphic_state"],
                    &format!("{path}.graphic_state"),
                )?,
                debug_info: scalar::<Option<bool>>(&value["debug_info"])?,
                fill_background: scalar::<Option<bool>>(&value["fill_background"])?,
                xobj_id: scalar::<Option<i64>>(&value["xobj_id"])?,
                line_width: scalar::<Option<f64>>(&value["line_width"])?,
                render_order: scalar::<Option<i64>>(&value["render_order"])?,
            }),
            "PdfStyle" => NodeData::PdfStyle(DataPdfStyle {
                graphic_state: self.optional(
                    "GraphicState",
                    &value["graphic_state"],
                    &format!("{path}.graphic_state"),
                )?,
                font_id: scalar::<Option<String>>(&value["font_id"])?,
                font_size: scalar::<Option<f64>>(&value["font_size"])?,
            }),
            "VisualBbox" => NodeData::VisualBbox(DataVisualBbox {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
            }),
            "PdfCharacter" => NodeData::PdfCharacter(DataPdfCharacter {
                pdf_style: self.optional(
                    "PdfStyle",
                    &value["pdf_style"],
                    &format!("{path}.pdf_style"),
                )?,
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
                visual_bbox: self.optional(
                    "VisualBbox",
                    &value["visual_bbox"],
                    &format!("{path}.visual_bbox"),
                )?,
                vertical: scalar::<Option<bool>>(&value["vertical"])?,
                scale: scalar::<Option<f64>>(&value["scale"])?,
                visual_roundtrip_text_scale_x: scalar::<Option<f64>>(
                    &value["visual_roundtrip_text_scale_x"],
                )?,
                visual_roundtrip_text_scale_y: scalar::<Option<f64>>(
                    &value["visual_roundtrip_text_scale_y"],
                )?,
                visual_roundtrip_text_render_mode: scalar::<Option<i64>>(
                    &value["visual_roundtrip_text_render_mode"],
                )?,
                pdf_character_id: scalar::<Option<i64>>(&value["pdf_character_id"])?,
                char_unicode: scalar::<Option<String>>(&value["char_unicode"])?,
                advance: scalar::<Option<f64>>(&value["advance"])?,
                xobj_id: scalar::<Option<i64>>(&value["xobj_id"])?,
                debug_info: scalar::<Option<bool>>(&value["debug_info"])?,
                formula_layout_id: scalar::<Option<i64>>(&value["formula_layout_id"])?,
                render_order: scalar::<Option<i64>>(&value["render_order"])?,
                sub_render_order: scalar::<Option<i64>>(&value["sub_render_order"])?,
            }),
            "PdfCurve" => NodeData::PdfCurve(DataPdfCurve {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
                graphic_state: self.optional(
                    "GraphicState",
                    &value["graphic_state"],
                    &format!("{path}.graphic_state"),
                )?,
                pdf_path: self.many("PdfPath", &value["pdf_path"], &format!("{path}.pdf_path"))?,
                pdf_original_path: self.many(
                    "PdfOriginalPath",
                    &value["pdf_original_path"],
                    &format!("{path}.pdf_original_path"),
                )?,
                pdf_original_path_primitive: self.optional(
                    "PdfOriginalPathPrimitive",
                    &value["pdf_original_path_primitive"],
                    &format!("{path}.pdf_original_path_primitive"),
                )?,
                debug_info: scalar::<Option<babeldoc_il_types::CurveDebugInfo>>(
                    &value["debug_info"],
                )?,
                fill_background: scalar::<Option<bool>>(&value["fill_background"])?,
                stroke_path: scalar::<Option<bool>>(&value["stroke_path"])?,
                evenodd: scalar::<Option<bool>>(&value["evenodd"])?,
                passthrough_paint: scalar::<Option<bool>>(&value["passthrough_paint"])?,
                xobj_id: scalar::<Option<i64>>(&value["xobj_id"])?,
                render_order: scalar::<Option<i64>>(&value["render_order"])?,
                ctm: (scalar::<Vec<babeldoc_il_types::PythonValue>>(&value["ctm"])?).into(),
                relocation_transform: scalar::<Vec<babeldoc_il_types::PythonValue>>(
                    &value["relocation_transform"],
                )?,
            }),
            "PdfForm" => NodeData::PdfForm(DataPdfForm {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
                graphic_state: self.optional(
                    "GraphicState",
                    &value["graphic_state"],
                    &format!("{path}.graphic_state"),
                )?,
                pdf_matrix: self.optional(
                    "PdfMatrix",
                    &value["pdf_matrix"],
                    &format!("{path}.pdf_matrix"),
                )?,
                pdf_affine_transform: self.optional(
                    "PdfAffineTransform",
                    &value["pdf_affine_transform"],
                    &format!("{path}.pdf_affine_transform"),
                )?,
                pdf_form_subtype: self.optional(
                    "PdfFormSubtype",
                    &value["pdf_form_subtype"],
                    &format!("{path}.pdf_form_subtype"),
                )?,
                xobj_id: scalar::<Option<i64>>(&value["xobj_id"])?,
                ctm: scalar::<Vec<babeldoc_il_types::PythonValue>>(&value["ctm"])?,
                relocation_transform: scalar::<Vec<babeldoc_il_types::PythonValue>>(
                    &value["relocation_transform"],
                )?,
                render_order: scalar::<Option<i64>>(&value["render_order"])?,
                form_type: scalar::<Option<String>>(&value["form_type"])?,
            }),
            "PdfSameStyleUnicodeCharacters" => {
                NodeData::PdfSameStyleUnicodeCharacters(DataPdfSameStyleUnicodeCharacters {
                    pdf_style: self.optional(
                        "PdfStyle",
                        &value["pdf_style"],
                        &format!("{path}.pdf_style"),
                    )?,
                    unicode: scalar::<Option<String>>(&value["unicode"])?,
                    debug_info: scalar::<Option<bool>>(&value["debug_info"])?,
                })
            }
            "PdfXobject" => NodeData::PdfXobject(DataPdfXobject {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
                pdf_font: self.many("PdfFont", &value["pdf_font"], &format!("{path}.pdf_font"))?,
                base_operations: self.optional(
                    "BaseOperations",
                    &value["base_operations"],
                    &format!("{path}.base_operations"),
                )?,
                xobj_id: scalar::<Option<i64>>(&value["xobj_id"])?,
                xref_id: scalar::<Option<i64>>(&value["xref_id"])?,
            }),
            "PdfFormula" => NodeData::PdfFormula(DataPdfFormula {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
                pdf_character: self.many(
                    "PdfCharacter",
                    &value["pdf_character"],
                    &format!("{path}.pdf_character"),
                )?,
                pdf_curve: self.many(
                    "PdfCurve",
                    &value["pdf_curve"],
                    &format!("{path}.pdf_curve"),
                )?,
                pdf_form: self.many("PdfForm", &value["pdf_form"], &format!("{path}.pdf_form"))?,
                x_offset: scalar::<Option<f64>>(&value["x_offset"])?,
                y_offset: scalar::<Option<f64>>(&value["y_offset"])?,
                x_advance: scalar::<Option<f64>>(&value["x_advance"])?,
                line_id: scalar::<Option<i64>>(&value["line_id"])?,
                is_corner_mark: scalar::<Option<bool>>(&value["is_corner_mark"])?,
            }),
            "PdfLine" => NodeData::PdfLine(DataPdfLine {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
                pdf_character: self.many(
                    "PdfCharacter",
                    &value["pdf_character"],
                    &format!("{path}.pdf_character"),
                )?,
                render_order: scalar::<Option<i64>>(&value["render_order"])?,
            }),
            "PdfSameStyleCharacters" => {
                NodeData::PdfSameStyleCharacters(DataPdfSameStyleCharacters {
                    r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
                    pdf_style: self.optional(
                        "PdfStyle",
                        &value["pdf_style"],
                        &format!("{path}.pdf_style"),
                    )?,
                    pdf_character: self.many(
                        "PdfCharacter",
                        &value["pdf_character"],
                        &format!("{path}.pdf_character"),
                    )?,
                })
            }
            "PdfParagraphComposition" => {
                NodeData::PdfParagraphComposition(DataPdfParagraphComposition {
                    pdf_line: self.optional(
                        "PdfLine",
                        &value["pdf_line"],
                        &format!("{path}.pdf_line"),
                    )?,
                    pdf_formula: self.optional(
                        "PdfFormula",
                        &value["pdf_formula"],
                        &format!("{path}.pdf_formula"),
                    )?,
                    pdf_same_style_characters: self.optional(
                        "PdfSameStyleCharacters",
                        &value["pdf_same_style_characters"],
                        &format!("{path}.pdf_same_style_characters"),
                    )?,
                    pdf_character: self.optional(
                        "PdfCharacter",
                        &value["pdf_character"],
                        &format!("{path}.pdf_character"),
                    )?,
                    pdf_same_style_unicode_characters: self.optional(
                        "PdfSameStyleUnicodeCharacters",
                        &value["pdf_same_style_unicode_characters"],
                        &format!("{path}.pdf_same_style_unicode_characters"),
                    )?,
                })
            }
            "PdfParagraph" => NodeData::PdfParagraph(DataPdfParagraph {
                r#box: self.optional("Box", &value["box"], &format!("{path}.box"))?,
                pdf_style: self.optional(
                    "PdfStyle",
                    &value["pdf_style"],
                    &format!("{path}.pdf_style"),
                )?,
                pdf_paragraph_composition: self.many(
                    "PdfParagraphComposition",
                    &value["pdf_paragraph_composition"],
                    &format!("{path}.pdf_paragraph_composition"),
                )?,
                xobj_id: scalar::<Option<i64>>(&value["xobj_id"])?,
                unicode: scalar::<Option<String>>(&value["unicode"])?,
                scale: scalar::<Option<f64>>(&value["scale"])?,
                optimal_scale: scalar::<Option<f64>>(&value["optimal_scale"])?,
                vertical: scalar::<Option<bool>>(&value["vertical"])?,
                first_line_indent: scalar::<Option<bool>>(&value["first_line_indent"])?,
                debug_id: scalar::<Option<String>>(&value["debug_id"])?,
                layout_label: scalar::<Option<String>>(&value["layout_label"])?,
                layout_id: scalar::<Option<i64>>(&value["layout_id"])?,
                render_order: scalar::<Option<i64>>(&value["render_order"])?,
            }),
            "Page" => NodeData::Page(DataPage {
                mediabox: self.optional(
                    "Mediabox",
                    &value["mediabox"],
                    &format!("{path}.mediabox"),
                )?,
                cropbox: self.optional("Cropbox", &value["cropbox"], &format!("{path}.cropbox"))?,
                pdf_xobject: self.many(
                    "PdfXobject",
                    &value["pdf_xobject"],
                    &format!("{path}.pdf_xobject"),
                )?,
                page_layout: self.many(
                    "PageLayout",
                    &value["page_layout"],
                    &format!("{path}.page_layout"),
                )?,
                pdf_rectangle: self.many(
                    "PdfRectangle",
                    &value["pdf_rectangle"],
                    &format!("{path}.pdf_rectangle"),
                )?,
                pdf_font: self.many("PdfFont", &value["pdf_font"], &format!("{path}.pdf_font"))?,
                pdf_paragraph: self.many(
                    "PdfParagraph",
                    &value["pdf_paragraph"],
                    &format!("{path}.pdf_paragraph"),
                )?,
                pdf_figure: self.many(
                    "PdfFigure",
                    &value["pdf_figure"],
                    &format!("{path}.pdf_figure"),
                )?,
                pdf_character: self.many(
                    "PdfCharacter",
                    &value["pdf_character"],
                    &format!("{path}.pdf_character"),
                )?,
                pdf_curve: self.many(
                    "PdfCurve",
                    &value["pdf_curve"],
                    &format!("{path}.pdf_curve"),
                )?,
                pdf_form: self.many("PdfForm", &value["pdf_form"], &format!("{path}.pdf_form"))?,
                base_operations: self.optional(
                    "BaseOperations",
                    &value["base_operations"],
                    &format!("{path}.base_operations"),
                )?,
                page_number: scalar::<Option<i64>>(&value["page_number"])?,
                unit: scalar::<Option<String>>(&value["unit"])?,
            }),
            "Document" => NodeData::Document(DataDocument {
                page: self.many("Page", &value["page"], &format!("{path}.page"))?,
                total_pages: scalar::<Option<i64>>(&value["total_pages"])?,
            }),
            _ => return Err(format!("unknown IL kind: {kind}").into()),
        })
    }
}
