//! Reconstruct the pinned upstream graph, including aliases and lazy instructions.
use babeldoc_ir_core::*;
use serde::de::DeserializeOwned;
use serde_json::Value;
use std::collections::HashMap;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn scalar<T: DeserializeOwned>(value: &Value) -> Result<T> {
    Ok(serde_json::from_value(value.clone())?)
}

struct Loader {
    table: Table,
    history: History,
    history_len: usize,
    aliases: HashMap<String, String>,
    loaded: HashMap<String, Edge>,
}

impl Loader {
    fn edge(&mut self, kind: &str, value: &Value, path: &str) -> Result<Edge> {
        let key = self.aliases.get(path).cloned();
        if let Some(edge) = key.as_ref().and_then(|key| self.loaded.get(key)) {
            return Ok(edge.share());
        }
        let data = self.data(kind, value, path)?;
        let edge = self.table.attach(Node::new(data));
        if let Some(key) = key {
            self.loaded.insert(key, edge.share());
        }
        Ok(edge)
    }

    fn optional(&mut self, kind: &str, value: &Value, path: &str) -> Result<Option<Edge>> {
        if value.is_null() {
            Ok(None)
        } else {
            Ok(Some(self.edge(kind, value, path)?))
        }
    }

    fn many(&mut self, kind: &str, value: &Value, path: &str) -> Result<Vec<Edge>> {
        value
            .as_array()
            .ok_or("expected an IL array")?
            .iter()
            .enumerate()
            .map(|(index, item)| self.edge(kind, item, &format!("{path}[{index}]")))
            .collect()
    }

    fn instructions(&self, value: &Value) -> Result<Option<Instructions>> {
        if value.is_null() {
            return Ok(None);
        }
        if let Some(text) = value.as_str() {
            return Ok(Some(Instructions::Materialized(text.into())));
        }
        if value["kind"] != "view" {
            return Err("unknown graphics-state instruction kind".into());
        }
        let tail: Option<usize> = scalar(&value["tail_ref"])?;
        if tail.is_some_and(|index| index >= self.history_len) {
            return Err("invalid graphics-state history reference".into());
        }
        Ok(Some(Instructions::View(InstructionView {
            tail,
            latest_versions: scalar(&value["latest_versions"])?,
            include_clipping: scalar(&value["include_clipping"])?,
            suffix_parts: scalar(&value["suffix_parts"])?,
        })))
    }
}

include!("generated.rs");

pub fn restore(artifact: &Value, strict: bool) -> Result<Document> {
    if artifact["schema_version"] != 1 {
        return Err("unsupported upstream artifact schema".into());
    }
    let mut loader = Loader {
        table: Table::default(),
        history: History::default(),
        history_len: 0,
        aliases: HashMap::new(),
        loaded: HashMap::new(),
    };
    for groups in artifact["shared_alias_paths"]
        .as_object()
        .ok_or("missing alias groups")?
        .values()
    {
        for paths in groups.as_array().ok_or("invalid alias groups")? {
            let paths: Vec<String> = scalar(paths)?;
            let key = paths.first().ok_or("empty alias group")?;
            for path in &paths {
                if loader.aliases.insert(path.clone(), key.clone()).is_some() {
                    return Err("duplicate alias path".into());
                }
            }
        }
    }
    for (index, record) in artifact["graphic_state_nodes"]
        .as_array()
        .ok_or("missing graphics-state history")?
        .iter()
        .enumerate()
    {
        if record["ordinal"].as_u64() != Some(index as u64) {
            return Err("non-sequential graphics-state history".into());
        }
        let parent: Option<usize> = scalar(&record["parent_ordinal"])?;
        if parent.is_some_and(|parent| parent >= index) {
            return Err("invalid graphics-state parent".into());
        }
        let arg = if let Some(text) = record["arg"].as_str() {
            HistoryArg::Text(text.into())
        } else {
            HistoryArg::CtmAware {
                value: scalar(&record["arg"]["value"])?,
                ctm: scalar(&record["arg"]["ctm"])?,
            }
        };
        loader.history.push(HistoryNode {
            parent,
            op: scalar(&record["op"])?,
            arg,
            replace_key: scalar(&record["replace_key"])?,
            version: scalar(&record["version"])?,
            length: scalar(&record["length"])?,
        });
        loader.history_len += 1;
    }
    let root = loader.data("Document", &artifact["document"], "$")?;
    let document = Document::from_parts(Node::new(root), loader.table, loader.history)?;
    if strict && document.artifact()? != *artifact {
        return Err("snapshot changed IL, aliases, or graphics-state history".into());
    }
    Ok(document)
}
