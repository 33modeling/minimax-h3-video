#!/usr/bin/env python3
"""Validate supplied startup resources before stopping services or loading models."""
import argparse
import csv
import io


def validate(rows, *, fl2va=True, ref2va=True, gpus='', ref_gpus='', available_ram=0, minimum_ram=0, cp=True, device_override=''):
    devices = {}
    for row in csv.reader(io.StringIO(rows)):
        if not row:
            continue
        index, used, total = [value.strip() for value in row]
        devices[index] = (int(used), int(total))
    errors = []
    groups = [value.split(',') if value else [] for value in (gpus, ref_gpus)]
    for group in groups:
        if len(group) != len(set(group)):
            errors.append('GPU 번호가 중복됐습니다.')
        for index in group:
            if index not in devices:
                errors.append(f'이 노드에 GPU {index}가 없습니다.')
    if set(groups[0]) & set(groups[1]):
        errors.append('FL2VA와 Ref2VA의 GPU가 겹칩니다.')
    if ref2va:
        required = 8 if fl2va else 4
        if len(devices) < required:
            errors.append(f'Ref2VA 포함 실행은 GPU {required}장 필요: 두 서버 4+4 또는 4장 노드 두 대에 각각 --fl2va-only / --ref-only. 2+2 자동 분할은 중단합니다.')
        assignments = sum(len(group) if group else 4 for enabled, group in [(fl2va, groups[0]), (ref2va, groups[1])] if enabled)
        if assignments > len(devices):
            errors.append(f'GPU 배정 합계 {assignments}장 > 이 노드 {len(devices)}장입니다. 각 서버의 GPU 집합을 확인하세요.')
        if sum(total >= 70 * 1024 for used, total in devices.values()) < required:
            errors.append(f'장당 70GiB 이상 VRAM인 GPU가 {required}장 필요합니다.')
        for enabled, label, group in [(fl2va, 'FL2VA', groups[0]), (ref2va, 'Ref2VA', groups[1])]:
            if enabled and group and len(group) < 4:
                errors.append(f'{label}에 최소 4장을 배정하세요. 현재 {len(group)}장입니다.')
            if enabled and group and any(devices.get(index, (0, 0))[1] < 70 * 1024 for index in group):
                errors.append(f'{label}: 장당 70GiB 이상 VRAM이 있는 GPU가 필요합니다. H100 80GB 구성을 확인하세요.')
        if not cp:
            errors.append('Ref2VA는 여러 GPU 방식이 필요합니다. H3_DSERVER_CP=0을 해제하세요.')
        if device_override and len([part for part in device_override.split(',') if part.strip()]) < 4:
            errors.append('H3_DSERVER_DEVICES가 4장 미만으로 고정돼 있습니다. 설정을 해제하세요.')
    if available_ram < minimum_ram:
        errors.append(f'CPU RAM 여유 {available_ram}GiB < 시작 검사 기준 {minimum_ram}GiB. GPU 4+4도 CPU RAM을 늘리지는 않습니다. 기존 H3 창을 Ctrl+C로 종료한 뒤 다시 확인하거나, 4장 노드 두 대에 서버를 하나씩 분리하세요. 이 기준은 실측 최대 사용량이 아닙니다.')
    return errors


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gpu-rows', required=True)
    p.add_argument('--mode', choices=['both', 'fl2va', 'ref2va'], default='both')
    p.add_argument('--gpus', default='')
    p.add_argument('--ref-gpus', default='')
    p.add_argument('--available-ram-gib', type=int, required=True)
    p.add_argument('--minimum-ram-gib', type=int, default=0)
    p.add_argument('--cp-disabled', action='store_true')
    p.add_argument('--device-override', default='')
    a = p.parse_args()
    errors = validate(a.gpu_rows, fl2va=a.mode != 'ref2va', ref2va=a.mode != 'fl2va', gpus=a.gpus, ref_gpus=a.ref_gpus, available_ram=a.available_ram_gib, minimum_ram=a.minimum_ram_gib, cp=not a.cp_disabled, device_override=a.device_override)
    for error in errors:
        print('[startup resources] ' + error)
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
