-- Road Risk car profile for the pinned OSRM toolchain.
--
-- Keep the upstream v6.0.0 driving behavior, but declare the hard-preference
-- classes owned by this application explicitly. The graph can therefore serve
-- the supported exclude=toll, exclude=motorway, and exclude=toll,motorway
-- request combinations.

local upstream_car = dofile('/opt/car.lua')
local upstream_setup = upstream_car.setup

local function setup()
  local profile = upstream_setup()
  profile.classes = Sequence {
    'toll', 'motorway', 'ferry', 'restricted', 'tunnel'
  }
  profile.excludable = Sequence {
    Set {'toll'},
    Set {'motorway'},
    Set {'toll', 'motorway'},
    Set {'ferry'}
  }
  return profile
end

return {
  setup = setup,
  process_way = upstream_car.process_way,
  process_node = upstream_car.process_node,
  process_turn = upstream_car.process_turn
}
