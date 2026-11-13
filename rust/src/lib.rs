//! Bridge-owned stage boundary. No translation providers or HTTP code live here.
mod snapshot;

use babeldoc_font_core::{FontFace, FontFamily, FontMapper, PrimaryFontFamily, SourceFontStyle};
use babeldoc_ir_core::{self as ir, ReadOnlyView, WriterView};
use babeldoc_p2_stages::stages::{
    layout_parser::{self, Coordinate, ModelBox, PageResult},
    paragraph_finder,
    paragraph_finder_inputs::{ParagraphFinderConfig, ParagraphFinderInputs, RandomDebugIdSource},
    styles_and_formulas,
    styles_and_formulas_config::StylesAndFormulasConfig,
    typesetting::Typesetting,
};
use babeldoc_p2_stages::{NoopCancellation, NoopProgress, StageContext};
use babeldoc_writer_core as writer;
use pyo3::{exceptions::PyRuntimeError, prelude::*};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::{
    collections::{BTreeMap, HashMap},
    path::PathBuf,
    sync::Arc,
};

const REVISION: &str = "d922e2b0c5a353bde8731921eb442c07ae75849d";
const SCHEMA: &str = "wenyi-babeldoc-native/v1";
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn error(error: impl std::fmt::Display) -> PyErr {
    PyRuntimeError::new_err(error.to_string())
}

#[derive(Deserialize)]
struct FontSpec {
    path: PathBuf,
    font_name: String,
    ascent: f64,
    descent: f64,
    encoding_length: i64,
}
#[derive(Deserialize)]
struct FontConfig {
    assets: BTreeMap<String, FontSpec>,
    normal: Vec<String>,
    script: Vec<String>,
    fallback: Vec<String>,
    base: Vec<String>,
    primary: Option<String>,
}
struct Fonts {
    config: FontConfig,
    faces: BTreeMap<String, Arc<FontFace>>,
    mapper: Arc<FontMapper>,
}
impl Fonts {
    fn load(json: &str) -> Result<Self> {
        let config: FontConfig = serde_json::from_str(json)?;
        let faces: BTreeMap<_, _> = config
            .assets
            .iter()
            .map(|(id, spec)| FontFace::load(id, &spec.path).map(|face| (id.clone(), face)))
            .collect::<std::result::Result<_, _>>()?;
        let group = |ids: &[String]| -> Result<Vec<Arc<FontFace>>> {
            ids.iter()
                .map(|id| {
                    faces
                        .get(id)
                        .cloned()
                        .ok_or_else(|| format!("missing font {id}").into())
                })
                .collect()
        };
        let mapper = FontMapper::new(
            FontFamily {
                normal: group(&config.normal)?,
                script: group(&config.script)?,
                fallback: group(&config.fallback)?,
                base: group(&config.base)?,
            },
            PrimaryFontFamily::from_option(config.primary.as_deref()),
        )?;
        Ok(Self {
            config,
            faces,
            mapper: Arc::new(mapper),
        })
    }
    fn source_styles(&self) -> Result<HashMap<String, SourceFontStyle>> {
        let mut styles = HashMap::new();
        for (id, face) in &self.faces {
            let flags = face.pdf_font_flags()?;
            let traits = face.traits();
            styles.insert(
                id.clone(),
                SourceFontStyle {
                    bold: traits.bold,
                    italic: traits.italic,
                    monospaced: traits.monospaced,
                    serif: flags.serif,
                },
            );
        }
        let base = self.config.base.first().ok_or("missing base font")?;
        styles.insert("base".into(), styles[base]);
        Ok(styles)
    }
}

#[pyclass(frozen, module = "wenyi_babeldoc_bridge._native")]
struct FontAssets {
    fonts: Arc<Fonts>,
}

#[pymethods]
impl FontAssets {
    #[new]
    fn new(py: Python<'_>, json: String) -> PyResult<Self> {
        py.detach(|| {
            Ok(Self {
                fonts: Arc::new(Fonts::load(&json).map_err(error)?),
            })
        })
    }
}

#[derive(Serialize, Deserialize)]
struct Snapshot {
    schema: String,
    revision: String,
    artifact: Value,
    page_objects: Vec<(u32, u16)>,
}

#[pyclass(module = "wenyi_babeldoc_bridge._native")]
struct Document {
    document: ir::Document,
    page_objects: Vec<(u32, u16)>,
}

#[derive(Deserialize)]
struct LayoutBox {
    xyxy: [f64; 4],
    precision: [u8; 4],
    conf: f64,
    class_name: String,
}
#[derive(Deserialize)]
struct LayoutPage {
    page_number: i64,
    mediabox: [f64; 2],
    boxes: Vec<LayoutBox>,
}

#[pymethods]
impl Document {
    #[staticmethod]
    #[pyo3(signature = (path, pages=None))]
    fn parse(py: Python<'_>, path: String, pages: Option<Vec<usize>>) -> PyResult<Self> {
        py.detach(move || {
            let parsed = babeldoc_parser_core::parse(
                path,
                babeldoc_parser_core::Config {
                    pages,
                    ..Default::default()
                },
            )
            .map_err(error)?;
            Ok(Self {
                document: parsed.document,
                page_objects: parsed.page_objects,
            })
        })
    }
    #[staticmethod]
    fn restore(py: Python<'_>, json: String) -> PyResult<Self> {
        py.detach(move || {
            let snapshot: Snapshot = serde_json::from_str(&json).map_err(error)?;
            if snapshot.schema != SCHEMA || snapshot.revision != REVISION {
                return Err(error(
                    "native snapshot version mismatch; extract the PDF again",
                ));
            }
            let document = snapshot::restore(&snapshot.artifact, true).map_err(error)?;
            if snapshot.page_objects.is_empty() {
                return Err(error("native snapshot is missing the parser page map"));
            }
            let view = document.read();
            for page in view.document().page_iter(&view).map_err(error)? {
                let number = page
                    .map_err(error)?
                    .page_number(&view)
                    .map_err(error)?
                    .ok_or_else(|| error("missing page number"))?;
                if number < 0 || number as usize >= snapshot.page_objects.len() {
                    return Err(error("native snapshot has an invalid page identity"));
                }
            }
            Ok(Self {
                document,
                page_objects: snapshot.page_objects,
            })
        })
    }
    fn snapshot(&self) -> PyResult<String> {
        serde_json::to_string(&Snapshot {
            schema: SCHEMA.into(),
            revision: REVISION.into(),
            artifact: self.document.artifact().map_err(error)?,
            page_objects: self.page_objects.clone(),
        })
        .map_err(error)
    }
    fn artifact(&self) -> PyResult<String> {
        serde_json::to_string(&self.document.artifact().map_err(error)?).map_err(error)
    }
    fn replace_artifact(&mut self, py: Python<'_>, json: String) -> PyResult<()> {
        py.detach(|| {
            let artifact = serde_json::from_str(&json).map_err(error)?;
            self.document = snapshot::restore(&artifact, false).map_err(error)?;
            Ok(())
        })
    }
    fn layout(&mut self, py: Python<'_>, json: String, debug: bool) -> PyResult<()> {
        py.detach(|| {
            let pages: Vec<LayoutPage> = serde_json::from_str(&json).map_err(error)?;
            let numbers = {
                let view = self.document.read();
                view.document()
                    .page_iter(&view)
                    .map_err(error)?
                    .map(|page| {
                        page?
                            .page_number(&view)?
                            .ok_or(ir::AccessError::UnknownSlot)
                    })
                    .collect::<std::result::Result<Vec<_>, _>>()
                    .map_err(error)?
            };
            for (index, number) in numbers.iter().enumerate() {
                let page = pages
                    .iter()
                    .find(|page| page.page_number == *number)
                    .ok_or_else(|| error("layout result missing for selected page"))?;
                let mut boxes = Vec::new();
                for item in &page.boxes {
                    if item.precision.iter().any(|bits| ![32, 64].contains(bits)) {
                        return Err(error("unsupported model coordinate precision"));
                    }
                    boxes.push(ModelBox {
                        xyxy: std::array::from_fn(|axis| {
                            if item.precision[axis] == 32 {
                                Coordinate::F32(item.xyxy[axis] as f32)
                            } else {
                                Coordinate::F64(item.xyxy[axis])
                            }
                        }),
                        conf: item.conf,
                        class_name: item.class_name.clone(),
                    });
                }
                layout_parser::apply_model(
                    &mut self.document,
                    &PageResult {
                        index: Some(index),
                        mediabox: Some(page.mediabox),
                        boxes,
                    },
                )
                .map_err(error)?;
            }
            layout_parser::fallback(&mut self.document, debug, &NoopProgress).map_err(error)
        })
    }
    fn paragraphs(
        &mut self,
        py: Python<'_>,
        fonts: PyRef<'_, FontAssets>,
        debug: bool,
        split_short_lines: bool,
        short_line_split_factor: f64,
    ) -> PyResult<()> {
        let fonts = Arc::clone(&fonts.fonts);
        py.detach(|| {
            paragraph_finder::process_with(
                &mut ParagraphFinderInputs {
                    config: &ParagraphFinderConfig {
                        debug,
                        split_short_lines,
                        short_line_split_factor,
                        ..Default::default()
                    },
                    font_mapper: &fonts.mapper,
                    debug_ids: &mut RandomDebugIdSource,
                },
                &mut self.document,
                &mut StageContext::new(&NoopCancellation, &NoopProgress),
            )
            .map_err(error)
        })
    }
    fn styles(&mut self, py: Python<'_>, fonts: PyRef<'_, FontAssets>) -> PyResult<()> {
        let fonts = Arc::clone(&fonts.fonts);
        py.detach(|| {
            styles_and_formulas::process(
                &StylesAndFormulasConfig::new((*fonts.mapper).clone()),
                &mut self.document,
                &mut StageContext::new(&NoopCancellation, &NoopProgress),
            )
            .map_err(error)
        })
    }
    fn typeset(
        &mut self,
        py: Python<'_>,
        fonts: PyRef<'_, FontAssets>,
        language: String,
    ) -> PyResult<()> {
        let fonts = Arc::clone(&fonts.fonts);
        py.detach(|| {
            let styles = fonts.source_styles().map_err(error)?;
            Typesetting::new(&language, Arc::clone(&fonts.mapper), true, styles)
                .process(
                    &mut self.document,
                    &mut StageContext::new(&NoopCancellation, &NoopProgress),
                )
                .map_err(error)
        })
    }
    fn write(
        &mut self,
        py: Python<'_>,
        source: String,
        output: String,
        fonts: PyRef<'_, FontAssets>,
    ) -> PyResult<()> {
        let fonts = Arc::clone(&fonts.fonts);
        py.detach(|| self.write_pdf(&source, &output, &fonts).map_err(error))
    }
}

impl Document {
    fn write_pdf(&mut self, source: &str, output: &str, fonts: &Fonts) -> Result<()> {
        let mut pdf = writer::PdfDocument::load(source)?;
        let page_objects = writer::PageObjectMap::new(self.page_objects.clone());
        let metadata: BTreeMap<_, _> = fonts
            .config
            .assets
            .iter()
            .map(|(id, spec)| {
                (
                    id.clone(),
                    writer::FontMetadata {
                        font_name: spec.font_name.clone(),
                        ascent: spec.ascent,
                        descent: spec.descent,
                        encoding_length: spec.encoding_length,
                    },
                )
            })
            .collect();
        let mut assets: Vec<_> = fonts
            .faces
            .iter()
            .map(|(id, face)| writer::FontAsset {
                id,
                face,
                metadata: &metadata[id],
            })
            .collect();
        let base = fonts.config.base.first().ok_or("missing base font")?;
        assets.push(writer::FontAsset {
            id: "base",
            face: &fonts.faces[base],
            metadata: &metadata[base],
        });
        let used = writer::used_font_ids(&self.document.view::<WriterView>())?;
        writer::add_fonts_with_used_ids_from_page_objects(
            &mut pdf,
            &mut self.document.view::<WriterView>(),
            &assets,
            &used,
            &page_objects,
            |_| Ok(()),
        )?;
        let view = self.document.view::<ReadOnlyView>();
        for page in view.document().page_iter(&view)? {
            let page = page?;
            let result = writer::build_page_output(&view, &page, &writer::BuildOptions::default())?;
            writer::apply_page_output_with_page_objects(&mut pdf, &result, &page_objects)?;
        }
        pdf.save(output)?;
        Ok(())
    }
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("BABELDOC_VERSION", "0.7.1")?;
    module.add("BABELDOC_REVISION", REVISION)?;
    module.add_class::<FontAssets>()?;
    module.add_class::<Document>()?;
    Ok(())
}
