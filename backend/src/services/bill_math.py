from decimal import Decimal, ROUND_HALF_UP

METER_TOLERANCE_KWH = Decimal('1.000')


def cents(value):
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_charges(actual_kwh, observed_peak_kw, tariff):
    expected_demand = max(observed_peak_kw, tariff['minimum_kw'])
    energy_charge = cents(actual_kwh * tariff['energy_rate'])
    demand_charge = cents(expected_demand * tariff['demand_rate'])
    return {
        'reconciled_kwh': actual_kwh,
        'expected_demand_kw': expected_demand,
        'energy_charge': energy_charge,
        'demand_charge': demand_charge,
        'expected_subtotal': energy_charge + demand_charge + tariff['fixed_fee'],
    }


def explain_exceptions(bill):
    meter_gap = bill['invoiced_kwh'] - bill['reconciled_kwh']
    demand_gap = bill['invoiced_demand_kw'] - bill['expected_demand_kw']
    charge_gap = bill['invoice_subtotal'] - bill['expected_subtotal']
    exceptions = []
    if abs(meter_gap) > METER_TOLERANCE_KWH:
        exceptions.append('meter_gap')
    if bill['demand_rate'] > 0 and demand_gap != 0:
        exceptions.append('demand_gap')
    if abs(charge_gap) > bill['charge_tolerance']:
        exceptions.append('charge_gap')
    return dict(meter_gap=meter_gap, demand_gap=demand_gap, charge_gap=charge_gap, exceptions=exceptions)
