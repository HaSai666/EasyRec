# -*- encoding:utf-8 -*-
# Copyright (c) Alibaba, Inc. and its affiliates.
import argparse
import json
import logging
import os

import nni
from hpo_nni.core.metric_utils import report_result
from hpo_nni.core.pyodps_utils import create_odps
from hpo_nni.core.pyodps_utils import kill_instance
from hpo_nni.core.pyodps_utils import run_command
from hpo_nni.core.utils import parse_ini
from hpo_nni.core.utils import set_value


def get_params():
  parser = argparse.ArgumentParser()
  parser.add_argument(
      '--config', type=str, help='config path', default='./config_begin.ini')
  parser.add_argument('--exp_dir', type=str, help='exp dir', default='../exp')
  args, _ = parser.parse_known_args()
  return args


if __name__ == '__main__':

  try:
    args = get_params()
    logging.info('args: %s', args)
    config = parse_ini(args.config)

    metric_dict = config['metric_config']
    logging.info('metric dict: %s', metric_dict)

    odps_config = config['odps_config']
    logging.info('odps_config: %s', odps_config)

    oss_config = config['oss_config']

    easyrec_cmd_config = config['easyrec_cmd_config']
    logging.info('easyrec_cmd_config: %s', easyrec_cmd_config)

    o = create_odps(
        access_id=oss_config['accessKeyID'],
        access_key=oss_config['accessKeySecret'],
        project=odps_config['project_name'],
        endpoint=odps_config['odps_endpoint'])

    # get parameters form tuner
    tuner_params = nni.get_next_parameter()

    # for tag
    experment_id = str(nni.get_experiment_id())
    trial_id = str(nni.get_trial_id())

    # for early stop,kill mc instance
    set_value('access_id', oss_config['accessKeyID'], trial_id=trial_id)
    set_value('access_key', oss_config['accessKeySecret'], trial_id=trial_id)
    set_value('project', odps_config['project_name'], trial_id=trial_id)
    set_value('endpoint', odps_config['odps_endpoint'], trial_id=trial_id)

    # update parameter
    pre_edit = eval(easyrec_cmd_config.get('-Dedit_config_json', '{}'))
    pre_edit.update(tuner_params)
    edit_json = json.dumps(pre_edit)
    easyrec_cmd_config['-Dedit_config_json'] = edit_json
    logging.info('-Dedit_config_json: %s',
                 easyrec_cmd_config['-Dedit_config_json'])

    # report metric
    easyrec_cmd_config['-Dmodel_dir'] = os.path.join(
        easyrec_cmd_config['-Dmodel_dir'], experment_id + '_' + trial_id)
    filepath = os.path.join(easyrec_cmd_config['-Dmodel_dir'], 'eval_val/')
    dst_filepath = os.path.join(args.exp_dir, experment_id + '_' + trial_id)
    logging.info('filepath: %s', filepath)
    logging.info('dst_file_path: %s', dst_filepath)
    report_result(
        filepath, dst_filepath, metric_dict, trial_id, oss_config=oss_config)

    # trial id for early stop
    run_command(o, easyrec_cmd_config, trial_id)

  except Exception:
    logging.exception('run begin error')
    exit(1)

  finally:
    # kill mc instance
    kill_instance(trial_job_id=trial_id)
    # for kill report result
    set_value(trial_id + '_exit', '1', trial_id=trial_id)
