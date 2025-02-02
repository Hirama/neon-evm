use serde::{ Deserialize };
use fern::{ Dispatch };
use std::{ process, path, ffi::OsStr };

#[derive(Deserialize)]
#[derive(Default)]
pub struct LogContext {
    req_id: String,
}

impl LogContext {
    pub fn new(id: String) -> LogContext {
        LogContext {
            req_id: id,
        }
    }
}


const LOG_MODULES: [&str; 11] = [
  "neon_cli",
  "neon_cli::account_storage",
  "neon_cli::commands::cancel_trx",
  "neon_cli::commands::create_ether_account",
  "neon_cli::commands::create_program_address",
  "neon_cli::commands::deploy",
  "neon_cli::commands::emulate",
  "neon_cli::commands::get_ether_account_data",
  "neon_cli::commands::get_neon_elf",
  "neon_cli::commands::get_storage_at",
  "neon_cli::commands::update_valids_table",
];


pub fn init(context: LogContext) -> Result<(), log::SetLoggerError> {

    let mut dispatch: Dispatch = fern::Dispatch::new().level(log::LevelFilter::Error);

    for module_name in LOG_MODULES {
        dispatch = dispatch.level_for(module_name, log::LevelFilter::Trace);
    }

    dispatch
        .format(move |out, message, record| {
            let line: String = record.line().map_or("NA".to_string(), |v| v.to_string());

            let file_name: &str = record.file()
                                        .and_then(|filepath| path::Path::new(filepath).file_name())
                                        .and_then(OsStr::to_str)
                                        .unwrap_or("Undefined");

            out.finish(format_args!(
                "{datetime:23} {level:.1} {file:}:{lineno:} {pid:} {component:}:{entity:} {context:} {message:}",
                datetime=chrono::Utc::now().format("%Y-%m-%d %H:%M:%S%.3f"),
                level=record.level(),
                file=file_name,
                lineno=line,
                pid=process::id(),
                component="Emulator",
                entity="Undefined",
                context=context.req_id,
                message=message
            ));
        })
        .chain(std::io::stderr())
        .apply()
}